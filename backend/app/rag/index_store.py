"""Immutable versions/projections and atomic successful-head persistence."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4
import math
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import db
from app.models import RagDocument, RagChunk, RagIndexProjection, RagIndexBatch, RagIndexState
from app.rag.contracts import RagIndexConflict, RagIndexUnavailable
from app.rag.identity import document_key, source_version_hash, profile_hash, digest
from app.rag.migration import require_rag_ready
from app.rag.storage_errors import storage_errors
from app.db_budget import budget_connection

SCOPE = 'repository-json'


def row_dict(row):
    return {c.name: deepcopy(getattr(row, c.name)) for c in row.__table__.columns}


def metadata(doc):
    defaults = {'schema_version': 1, 'source_ref': '', 'source_url': ''}
    fields = ('metric_keys','dimensions','concept_ids','aliases','source_type','source_ref','source_url',
              'valid_from','valid_to','reviewed_by','updated_at','schema_version','wiki_card','governance')
    return {k: deepcopy(doc.get(k, defaults.get(k))) for k in fields}


def assert_immutable(documents, stored_versions):
    for doc in documents:
        row = stored_versions.get(document_key(doc))
        if not row: continue
        if row['source_version_hash']:
            if row['source_version_hash'] != source_version_hash(doc):
                raise RagIndexConflict('document_version_conflict')
        else:
            for key in ('title','content','status','knowledge_type'):
                if row[key] != doc[key]: raise RagIndexUnavailable('migration_conflict')
            expected = metadata(doc); old = row['metadata_json'] or {}
            for key, value in old.items():
                if key in expected and value != expected[key]: raise RagIndexUnavailable('migration_conflict')
            if not set(expected) <= set(old): raise RagIndexUnavailable('migration_not_ready')


def validate_projection(projection):
    try:
        profile = {k:v for k,v in projection['profile_json'].items() if k!='responseModel'}
        if profile_hash(profile) != projection['profile_hash']: raise ValueError('profile hash')
        if not projection['chunks_json']: raise ValueError('missing chunks')
        for index, chunk in enumerate(projection['chunks_json']):
            sha = digest(chunk['content'])
            vector = chunk['embedding']
            if (chunk['document_pk'] != projection['document_pk'] or
                f"{chunk['document_id']}@{chunk['version']}" != projection['document_pk'] or
                chunk['chunk_index'] != index or chunk['content_hash'] != sha or
                chunk['chunk_id'] != f"{projection['document_pk']}#{index}-{sha[:12]}" or
                chunk['embedding_input_hash'] != digest(chunk['title']+'\n'+chunk['content']) or
                chunk['embedding_provider'] != profile['provider'] or chunk['embedding_model'] != profile['model'] or
                not isinstance(vector,list) or len(vector)!=profile['dimensions'] or
                not all(type(x) in (int,float) and math.isfinite(x) for x in vector)):
                raise ValueError('chunk integrity')
    except (KeyError,ValueError,TypeError) as exc:
        raise RagIndexUnavailable('index_corrupt') from exc


class RagIndexStore:
    @storage_errors
    def read_snapshot(self, *, connection=None, documents=None, consume_row=None, admit_rows=None):
        engine = connection.engine if connection is not None else db.get_engine()
        # All head, document, projection and origin reads share one PG MVCC view.
        options = {'isolation_level': 'REPEATABLE READ'} if engine.dialect.name == 'postgresql' else {}
        with (nullcontext(connection) if connection is not None else budget_connection(engine)) as acquired:
            conn=acquired if connection is not None else acquired.execution_options(**options)
            require_rag_ready(engine,connection=conn)
            with Session(conn) as session:
                def copied(row):
                    value=row_dict(row)
                    if consume_row:consume_row(row.__tablename__,value)
                    return value
                if admit_rows:admit_rows(session,RagIndexState,RagIndexState.scope==SCOPE)
                state = session.get(RagIndexState, SCOPE)
                state_value=copied(state) if state else None
                head = state_value['head_batch_id'] if state_value else None
                if head and admit_rows:admit_rows(session,RagIndexBatch,RagIndexBatch.batch_id==head)
                batch = session.get(RagIndexBatch, head) if head else None
                batch_value=copied(batch) if batch else None
                if admit_rows:admit_rows(session,RagDocument)
                versions = {r.pk: copied(r) for r in session.scalars(select(RagDocument).execution_options(yield_per=100))}
                if admit_rows:admit_rows(session,RagIndexProjection)
                projections = {r.projection_id: copied(r) for r in session.scalars(select(RagIndexProjection).execution_options(yield_per=100))}
                from app.wiki.eligibility import origin_states
                candidate_ids = {((r['source_snapshot'] or {}).get('governance') or {}).get('origin', {}).get('candidate_id') for r in versions.values()}
                candidate_ids.update(((d.get('governance') or {}).get('origin') or {}).get('candidate_id') for d in (documents or []))
                origins=origin_states(session,candidate_ids,consume_row=consume_row,admit_rows=admit_rows)
                return {'head': head, 'revision': state_value['revision'] if state_value else 0,
                        'batch': batch_value, 'versions': versions,
                        'projections': projections, 'origins': origins,
                        'manifest': deepcopy(batch_value['manifest_json']) if batch_value else {'versions':{},'projections':{},'barriers':{}}}

    @storage_errors
    def commit_batch(self, documents, projections, manifest, report, *, expected_head, commit_guard, connection):
        now = datetime.now(timezone.utc).isoformat()
        with Session(connection) as session:
            try:
                state = session.scalar(select(RagIndexState).where(RagIndexState.scope==SCOPE).with_for_update())
                if (state.head_batch_id if state else None) != expected_head: raise RagIndexConflict('head_changed')
                stored = {r.pk: row_dict(r) for r in session.scalars(select(RagDocument))}
                assert_immutable(documents, stored)
                identities={}
                def remember(chunk_id,sha):
                    if chunk_id in identities and identities[chunk_id]!=sha:
                        raise RagIndexUnavailable('chunk_identity_conflict')
                    identities[chunk_id]=sha
                for row in session.execute(select(RagChunk.chunk_id,RagChunk.content)):
                    remember(row.chunk_id,digest(row.content))
                retained={r.projection_id:row_dict(r) for r in session.scalars(select(RagIndexProjection))}
                for projection in [*retained.values(),*projections]:
                    validate_projection(projection)
                    previous=retained.get(projection['projection_id'])
                    if previous and any(previous[k]!=projection[k] for k in ('document_pk','source_version_hash','profile_hash','chunks_json')):
                        raise RagIndexUnavailable('index_corrupt')
                    for chunk in projection['chunks_json']:remember(chunk['chunk_id'],chunk['content_hash'])
                imported = unchanged = 0
                for doc in documents:
                    key = document_key(doc); row = session.get(RagDocument,key)
                    if row is None:
                        row = RagDocument(pk=key, document_id=doc['id'], version=doc['version'],title=doc['title'],
                            knowledge_type=doc['knowledge_type'],status=doc['status'],content=doc['content'],
                            content_hash=source_version_hash(doc),metadata_json=metadata(doc),active=False,
                            created_at=now,updated_at=now)
                        session.add(row); imported+=1
                    else: unchanged+=1
                    if row.source_version_hash is None:
                        row.source_snapshot=deepcopy(doc);row.source_version_hash=source_version_hash(doc)
                for projection in projections:
                    if session.get(RagIndexProjection, projection['projection_id']) is None:
                        session.add(RagIndexProjection(**deepcopy(projection), created_at=now))
                batch_id='b-'+uuid4().hex
                final={**report,'imported':imported,'unchanged':unchanged,'updated':0,
                       'previousBatchId':expected_head,'indexBatchId':batch_id}
                session.add(RagIndexBatch(batch_id=batch_id,source_revision=report['sourceRevision'],
                    profile_hash=report['embeddingProfileHash'],manifest_json=deepcopy(manifest),report_json=final,created_at=now))
                if state is None:state=RagIndexState(scope=SCOPE,revision=0);session.add(state)
                state.head_batch_id=batch_id;state.revision+=1
                session.flush();commit_guard();session.commit()
                return final
            except Exception:
                session.rollback();raise
