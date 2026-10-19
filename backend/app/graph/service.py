"""Local deterministic build coordinator; graph locks are last in the source protocol."""
from contextlib import contextmanager
import os
import threading
import time
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.db_budget import budget_connection,budget_scope
from app.graph.contracts import GraphError,GraphLimits,Budget,resolve_pointer
from app.graph.source import SourceReader
from app.graph.projector import project
from app.graph.store import GraphStore
from app.graph.migrations import require_graph_ready
from app.business_version import canonical_hash
from app.rag.contracts import RagIndexUnavailable
from app.runtime.contracts import RuntimeFailure

_sqlite_build_lock=threading.Lock()
BUILD_KEY=int.from_bytes(bytes.fromhex(canonical_hash('dora-graph-v1'))[:8],'big',signed=True)


@contextmanager
def build_lock(engine,budget):
    with budget_connection(engine,budget) as connection:
        acquired=False
        try:
            while not acquired:
                budget.check()
                if engine.dialect.name=='postgresql':
                    acquired=connection.execute(text('SELECT pg_try_advisory_lock(:key)'),{'key':BUILD_KEY}).scalar()
                    connection.commit()
                else:acquired=_sqlite_build_lock.acquire(blocking=False)
                if not acquired:time.sleep(min(.02,budget.remaining()))
            yield connection
        finally:
            if connection.in_transaction():connection.rollback()
            if acquired:
                if engine.dialect.name=='postgresql':
                    try:
                        connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':BUILD_KEY});connection.commit()
                    except Exception:connection.invalidate()
                else:_sqlite_build_lock.release()


def verify_witness(witness,view):
    source=view['records'].get(witness['sourceKey'])
    if not source or source['hash']!=witness['sourceHash'] or resolve_pointer(source['data'],witness['pointer'])!=witness['data']:
        raise GraphError('graph_integrity_unavailable')
    return source


class GraphService:
    def __init__(self,engine=None,source=None,*,limits=None):
        self.engine=engine or db.get_engine();self.limits=limits or GraphLimits()
        self.reader=SourceReader(self.engine,source,limits=self.limits);self.store=GraphStore(self.limits)
    def ready(self,budget=None):
        if budget is not None: budget.check()
        if os.environ.get('DORA_GRAPH_ENABLED','true').lower() not in {'true','1'}:raise GraphError('graph_disabled')
        with budget_scope(budget): require_graph_ready(self.engine)
        if budget is not None: budget.check()
    def sync(self,*,rebuild=False,budget=None,expected_head=None):
        budget=budget or Budget(self.limits.buildAdmissionMs);self.ready(budget);budget.check()
        try:
            with build_lock(self.engine,budget) as connection:
                view=self.reader.capture(budget);graph=project(view,self.limits,budget)
                with Session(connection) as session:
                    base=self.store.head(session)
                if connection.in_transaction():connection.rollback()
                if expected_head is not None and expected_head!=base:raise GraphError('head_changed',409)
                with connection.begin(),Session(connection) as session:
                    if connection.dialect.name=='sqlite':connection.exec_driver_sql('BEGIN IMMEDIATE')
                    self.reader.lock_sources(session,budget)
                    with self.reader.source.locked_snapshot(budget=budget,max_bytes=self.limits.maxSourceBytes) as current_file:
                        current=self.reader.capture(budget,connection=connection,locked_file=current_file)
                        if current['vector']!=view['vector']:raise GraphError('source_changed',409)
                        result=self.store.commit(session,graph,expected_head=base,budget=budget)
                        session.flush();budget.check()
                return {**result,'rebuilt':bool(rebuild),'nodes':len(graph['nodes']),'relations':len(graph['relations']),
                        'witnesses':len(graph['evidence']),'missingEvidence':graph['missingEvidence'],'externalModelCalls':0}
        except SQLAlchemyError as exc:raise GraphError('graph_unavailable') from exc
        except RagIndexUnavailable as exc:raise GraphError('source_unavailable') from exc
        except RuntimeFailure as exc:raise GraphError('build_input_limit',422) from exc
    def status(self):
        budget=Budget(self.limits.queryAdmissionMs)
        with self.read_view(budget) as (batch,view):
            value=dict(ready=bool(batch),batchId=batch['batchId'] if batch else None,
                graphRevision=batch['graph']['graphRevision'] if batch else None,
                sourceState='in_sync' if batch and batch['graph']['sourceVector']==view['vector'] else 'pending')
            budget.check();return value
    @contextmanager
    def read_view(self,budget,batch_id=None,*,full=False):
        self.ready(budget)
        try:
            with self.reader.source.locked_snapshot(budget=budget,max_bytes=self.limits.maxSourceBytes) as source:
                options={'isolation_level':'REPEATABLE READ'} if self.engine.dialect.name=='postgresql' else {}
                with budget_connection(self.engine,budget) as connection:
                    connection=connection.execution_options(**options)
                    with connection.begin():
                        if connection.dialect.name=='sqlite':connection.exec_driver_sql('BEGIN')
                        with Session(connection) as session:
                            if full:
                                view=self.reader.capture(budget,connection=connection,locked_file=source)
                                batch=self.store.read_batch(session,batch_id,budget=budget)
                            else:
                                batch=self.store.read_metadata(session,batch_id,budget=budget)
                                view=self.reader.for_batch(session,source,batch['graph']['sourceVector'],budget) if batch else {'vector':None}
                                if batch:batch.update(store=self.store,session=session)
                            yield batch,view
        except SQLAlchemyError as exc:raise GraphError('graph_unavailable') from exc
        except RagIndexUnavailable as exc:raise GraphError('source_unavailable') from exc
        except RuntimeFailure as exc:raise GraphError('build_input_limit',422) from exc
    def reconcile(self):
        issues=[];batch=None;view=None
        try:
            with self.read_view(Budget(self.limits.buildAdmissionMs),full=True) as (batch,view):
                if not batch:issues.append('graph_not_ready')
                else:
                    for witness in batch['graph']['evidence']:verify_witness(witness,view)
                    if batch['graph']['sourceVector']!=view['vector']:issues.append('source_changed')
        except GraphError as exc:issues.append(exc.code)
        return dict(ok=not issues,issues=issues,batchId=batch['batchId'] if batch else None,readOnly=True)
    def neighborhood(self,request):
        from app.graph.query import traversal
        budget=Budget(self.limits.queryAdmissionMs)
        with self.read_view(budget,request.batchId) as (batch,view):
            if batch is None:raise GraphError('graph_not_ready')
            return traversal(batch,view,request,self.limits,budget)
    def evidence(self,relation_id,batch_id,*,include_simulated=False):
        from app.graph.contracts import GraphRequest
        from app.graph.query import relation_evidence
        budget=Budget(self.limits.queryAdmissionMs)
        request=GraphRequest(entityId='evidence',mode='historical',batchId=batch_id,includeSimulated=include_simulated)
        with self.read_view(budget,batch_id) as (batch,view):
            if batch is None:raise GraphError('graph_not_ready')
            return relation_evidence(batch,view,request,relation_id,self.limits,budget)
