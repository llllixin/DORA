"""One bounded read-only MVCC capture, without fetching vector payloads."""
from copy import deepcopy
from datetime import datetime
import time
from zoneinfo import ZoneInfo
from sqlalchemy import LargeBinary, Text, cast, func, literal, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.db_budget import budget_connection
from app.models import RagDocument, RagIndexState, RagIndexBatch, RagIndexProjection
from app.rag.contracts import RagIndexConflict, RagIndexUnavailable
from app.rag.identity import canonical, document_key, embedding_profile, profile_hash
from app.rag.index_store import assert_immutable
from app.rag.migration import require_rag_ready
from app.runtime.contracts import RuntimeFailure
from app.wiki.catalog import CatalogError, CatalogSnapshot
from app.wiki.eligibility import origin_states


class CatalogBudget:
    def __init__(self, seconds=5):
        self.end=time.monotonic()+seconds;self.rows=0;self.bytes=0
    def remaining(self):return max(0.,self.end-time.monotonic())
    def check(self):
        if self.remaining()<=0:raise CatalogError('catalog_deadline_exceeded')
    def consume(self,table,row):
        self.check();self.rows+=1;self.bytes+=len(canonical(row).encode('utf-8'))
        if self.rows>10000 or self.bytes>2097152:raise CatalogError('catalog_input_limit')
    def admit(self,session,model,*criteria,columns=None):
        """Measure only selected fields before allocating text/JSON in Python."""
        self.check();columns=columns if columns is not None else list(model.__table__.columns)
        size=literal(2)
        for col in columns:
            length=(func.octet_length(cast(col,Text)) if session.bind.dialect.name=='postgresql'
                    else func.length(cast(col,LargeBinary)))
            size+=literal(len(col.name.encode('utf-8'))+4)+func.coalesce(length,4)
        bounded=select(size.label('bytes')).select_from(model).where(*criteria).subquery()
        count,total=session.execute(select(func.count(),func.coalesce(func.sum(bounded.c.bytes),0))).one()
        self.check()
        if count>10000-self.rows or total>2097152-self.bytes:raise CatalogError('catalog_input_limit')


def _read(session, budget, model, columns, *criteria):
    budget.admit(session,model,*criteria,columns=columns)
    values=[]
    for row in session.execute(select(*columns).where(*criteria).execution_options(yield_per=100)).mappings():
        value=deepcopy(dict(row));budget.consume(model.__tablename__,value);values.append(value)
    return values


class CatalogStore:
    def __init__(self, engine, source, *, now=None):
        self.engine,self.source=engine,source
        self.now=now or (lambda:datetime.now(ZoneInfo('Asia/Shanghai')))
    def after_database(self):pass
    def capture(self, *, budget=None):
        budget=budget or CatalogBudget()
        day=self.now().astimezone(ZoneInfo('Asia/Shanghai')).date()
        try:
            source=self.source.snapshot(on_date=day,budget=budget,max_bytes=2097152-budget.bytes)
            for document in source.documents:budget.consume('wiki',document)
            options={'isolation_level':'REPEATABLE READ'} if self.engine.dialect.name=='postgresql' else {}
            with budget_connection(self.engine,budget) as bounded:
                connection=bounded.execution_options(**options)
                with connection.begin():
                    if connection.dialect.name=='postgresql':connection.execute(text('SET TRANSACTION READ ONLY'))
                    require_rag_ready(self.engine,connection=connection)
                    with Session(connection,autoflush=False) as session:
                        head_rows=_read(session,budget,RagIndexState,[RagIndexState.scope,RagIndexState.head_batch_id,RagIndexState.revision],RagIndexState.scope=='repository-json')
                        head=head_rows[0]['head_batch_id'] if head_rows else None
                        batches=_read(session,budget,RagIndexBatch,[RagIndexBatch.batch_id,RagIndexBatch.source_revision,RagIndexBatch.profile_hash,RagIndexBatch.manifest_json],RagIndexBatch.batch_id==head) if head else []
                        if head and not batches:raise CatalogError('catalog_head_unavailable')
                        batch=batches[0] if batches else None
                        manifest=batch['manifest_json'] if batch else {'versions':{},'projections':{},'barriers':{}}
                        if not all(isinstance(manifest.get(k),dict) for k in ('versions','projections','barriers')):
                            raise CatalogError('catalog_manifest_unavailable')
                        # Hash rows are small even when old source snapshots are huge.
                        stored=_read(session,budget,RagDocument,[RagDocument.pk,RagDocument.source_version_hash])
                        hashes={row['pk']:row for row in stored}
                        legacy={row['pk'] for row in stored if not row['source_version_hash']}
                        relevant=legacy & {document_key(doc) for doc in source.documents}
                        if relevant:
                            compatibility=_read(session,budget,RagDocument,[RagDocument.pk,RagDocument.source_version_hash,RagDocument.title,RagDocument.content,RagDocument.status,RagDocument.knowledge_type,RagDocument.metadata_json],RagDocument.pk.in_(relevant))
                            hashes.update({row['pk']:row for row in compatibility})
                        assert_immutable(source.documents,hashes)
                        projection_ids=list(manifest['projections'].values())
                        headers=_read(session,budget,RagIndexProjection,[RagIndexProjection.projection_id,RagIndexProjection.document_pk,RagIndexProjection.source_version_hash,RagIndexProjection.profile_hash],RagIndexProjection.projection_id.in_(projection_ids)) if projection_ids else []
                        candidates={((d.get('governance') or {}).get('origin') or {}).get('candidate_id') for d in source.documents}
                        origins=origin_states(session,candidates,consume_row=budget.consume,admit_rows=budget.admit)
            self.after_database();budget.check()
            recheck=self.source.snapshot(on_date=day,budget=budget,max_bytes=2097152-budget.bytes)
            for document in recheck.documents:budget.consume('wiki_recheck',document)
            if source.revision!=recheck.revision:raise CatalogError('catalog_source_changed',409)
            from app.rag.embeddings import resolve_embedding_provider
            desired=profile_hash(embedding_profile(resolve_embedding_provider()))
            budget.check()
            return CatalogSnapshot(source,day,deepcopy(manifest),hashes,origins,
                                   {row['projection_id']:row for row in headers},head,batch,desired)
        except CatalogError:raise
        except RagIndexConflict as exc:raise CatalogError(exc.code,409) from exc
        except (RagIndexUnavailable,RuntimeFailure) as exc:
            raise CatalogError(exc.code,409 if exc.code=='migration_conflict' else 503) from exc
        except (SQLAlchemyError,self.engine.dialect.loaded_dbapi.Error) as exc:
            budget.check();raise CatalogError('catalog_database_unavailable') from exc
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            raise CatalogError('catalog_source_unavailable') from exc
