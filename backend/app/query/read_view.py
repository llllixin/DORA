"""One bounded MVCC view; file capture/recheck brackets the read transaction."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.business_store import freeze_business_inputs
from app.models import KnowledgeArchive,KnowledgeCandidate,ActionCase
from app.query.contracts import ReadLimits,ReadPolicy,effective_limits,QueryUnavailable,QueryConflict
from app.rag.contracts import RagIndexUnavailable,RagIndexConflict
from app.rag.identity import canonical
from app.rag.index_store import RagIndexStore,row_dict
from app.runtime.contracts import RuntimeFailure
from app.db_budget import budget_connection

class CaptureBudget:
    def __init__(self,limits,run_budget):self.limits=limits;self.run_budget=run_budget;self.rows=0;self.bytes=0
    def consume(self,table,row):
        self.run_budget.check();self.rows+=1;self.bytes+=len(canonical(row).encode('utf-8'))
        if self.rows>self.limits.maxReadViewRows or self.bytes>self.limits.maxReadViewBytes:raise RuntimeFailure('read_view_limit')
    def admit(self,session,model,*criteria,order_by=(),limit=None):
        from app.read_admission import admit_payloads
        admit_payloads(session,model,remaining_rows=self.limits.maxReadViewRows-self.rows,
                       remaining_bytes=self.limits.maxReadViewBytes-self.bytes,check=self.run_budget.check,
                       criteria=criteria,order_by=order_by,limit=limit)

class QueryReadView:
    def __init__(self,*,source,business,indexState,archives,archiveOrigins,sourceStates,readAt,businessDate):
        self.source=source;self.business=business
        self._indexState=deepcopy(indexState);self._archives=deepcopy(archives);self._archiveOrigins=deepcopy(archiveOrigins)
        self._sourceStates=deepcopy(sourceStates);self.readAt=readAt;self.businessDate=businessDate
    @property
    def indexState(self):return deepcopy(self._indexState)
    @property
    def archives(self):return deepcopy(self._archives)
    @property
    def archiveOrigins(self):return deepcopy(self._archiveOrigins)
    @property
    def sourceStates(self):return deepcopy(self._sourceStates)

class QueryReadViewReader:
    def __init__(self,engine,source,policy=None,*,now=None):
        self.engine=engine;self.source=source;self.policy=policy or ReadPolicy()
        self.now=now or (lambda:datetime.now(ZoneInfo('Asia/Shanghai')))
    def after_database(self):pass
    def capture(self,plan,*,run_context,read_at=None):
        stamp=read_at or self.now();day=plan.businessDate or stamp.astimezone(ZoneInfo('Asia/Shanghai')).date()
        budget=run_context.budget;limits=effective_limits(run_context);capture=CaptureBudget(limits,budget)
        states={};source=None;business=None;index=None;archives=[];origins={}
        if 'wiki' in plan.sourceKinds:
            try:
                source=self.source.snapshot(on_date=day,budget=budget,max_bytes=limits.maxReadViewBytes)
                for doc in source.documents:capture.consume('wiki',doc)
            except RagIndexUnavailable as exc:states['wiki']={'state':'unavailable','reasonCode':exc.code}
        options={'isolation_level':'REPEATABLE READ'} if self.engine.dialect.name=='postgresql' else {}
        try:
            with budget_connection(self.engine,budget,statement_ms=limits.maxReadStatementMs) as bounded_conn:
                conn=bounded_conn.execution_options(**options)
                with conn.begin():
                    budget.check()
                    if conn.dialect.name=='postgresql':
                        conn.execute(text('SET TRANSACTION READ ONLY'))
                        conn.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),{'timeout':str(max(1,min(limits.maxReadStatementMs,int(budget.remaining()*1000))))})
                    with Session(conn) as session:
                        if 'business' in plan.sourceKinds:
                            try:business=freeze_business_inputs(session,consume_row=capture.consume,check_deadline=budget.check,admit_rows=capture.admit)
                            except SQLAlchemyError:raise
                            except __import__('app.repository',fromlist=['DataSourceUnavailableError']).DataSourceUnavailableError:
                                states['business']={'state':'unavailable','reasonCode':'data_source_unavailable'}
                        if 'archive' in plan.sourceKinds:
                            for model in (KnowledgeArchive,KnowledgeCandidate,ActionCase):
                                capture.admit(session,model)
                                values=[]
                                for row in session.scalars(select(model).execution_options(yield_per=100)):
                                    value=row_dict(row);capture.consume(model.__tablename__,value);values.append(value)
                                if model is KnowledgeArchive:archives=values
                                elif model is KnowledgeCandidate:origins['candidates']=values
                                else:origins['cases']=values
                    if source is not None:
                        try:index=RagIndexStore().read_snapshot(connection=conn,documents=source.documents,consume_row=capture.consume,admit_rows=capture.admit)
                        except RagIndexUnavailable as exc:
                            # Logical readiness can be partial. A failed SQL statement
                            # invalidates the whole transaction; never stitch a new view.
                            if isinstance(exc.__cause__,SQLAlchemyError):raise QueryUnavailable('data_source_unavailable') from exc
                            states['wiki']={'state':'unavailable','reasonCode':exc.code}
                        except RagIndexConflict as exc:raise QueryConflict(exc.code) from exc
        except SQLAlchemyError as exc:
            budget.check()
            code='read_timeout' if getattr(getattr(exc,'orig',None),'sqlstate',None)=='57014' else 'data_source_unavailable'
            raise QueryUnavailable(code) from exc
        self.after_database();budget.check()
        if source is not None:
            recheck=self.source.snapshot(on_date=day,budget=budget,max_bytes=limits.maxReadViewBytes)
            if recheck.revision!=source.revision:raise QueryConflict('read_view_changed')
        for kind in plan.sourceKinds:states.setdefault(kind,{'state':'ready','reasonCode':None})
        return QueryReadView(source=source,business=business,indexState=index,archives=archives,archiveOrigins=origins,
                             sourceStates=states,readAt=stamp.isoformat(),businessDate=day)
