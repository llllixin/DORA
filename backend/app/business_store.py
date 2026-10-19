"""Scope-locked writes and a single business read view, separate from Action locks."""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from inspect import signature
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import db
from app.db_budget import budget_scope, guard_budget, current_budget, prepare_session as prepare_budget_session, budget_connection
from app.business_version import SCOPE_ID, FrozenBusiness, build_version, cache_key, occurrence_id, reasoning_input_hash
from app.models import BusinessRevision, DataUpdateLog, InsightReasoning, MetricSeries, RuleConfig, StoreClusterStore, VersionedReasoning


def _insert(session, model):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(model)


def initialize_scope(session):
    session.execute(_insert(session, BusinessRevision).values(scope_id=SCOPE_ID, source_epoch=str(uuid4()),
                                                            generation=0, source_manifest={})
                    .on_conflict_do_nothing(index_elements=["scope_id"]))


def init_business_revision(engine):
    with Session(engine) as session:
        initialize_scope(session)
        session.commit()


def _raw_inputs(session, state, *, consume_row=None, check_deadline=None, admit_rows=None):
    from app.repository import _cast
    def read(model):
        result=[]
        if admit_rows:admit_rows(session,model)
        for row in session.execute(select(model).execution_options(yield_per=100)).scalars():
            if check_deadline: check_deadline()
            if consume_row: consume_row(model.__tablename__, {c.name: deepcopy(getattr(row,c.name)) for c in model.__table__.columns})
            result.append(row)
        return result
    if check_deadline: check_deadline()
    if consume_row: consume_row('business_revision',{c.name:deepcopy(getattr(state,c.name)) for c in state.__table__.columns})
    rows,clusters,rules = read(MetricSeries),read(StoreClusterStore),read(RuleConfig)
    if admit_rows:admit_rows(session,DataUpdateLog,order_by=(DataUpdateLog.id.desc(),),limit=1)
    event = session.execute(select(DataUpdateLog).order_by(DataUpdateLog.id.desc()).limit(1)).scalar_one_or_none()
    if event is not None and consume_row: consume_row('data_update_log',{c.name:deepcopy(getattr(event,c.name)) for c in event.__table__.columns})
    return dict(scopeId=state.scope_id, sourceEpoch=state.source_epoch, generation=state.generation,
                rows=[dict(metric_key=r.metric_key, label=r.label, dimension=r.dimension, value=r.value, unit=r.unit, rowId=r.id) for r in rows],
                clusters=[dict(store=r.store, region=r.region, aov=r.aov) for r in clusters],
                rules={r.key: _cast(r.value, r.value_type) for r in rules},
                ruleRows=[dict(key=r.key, value=r.value, value_type=r.value_type) for r in rules],
                event=dict(eventId=event.id, updated=event.updated_at, rows_added=event.rows_added,
                           total_rows=event.total_rows, metrics=event.metrics) if event else None,
                sourceManifest=deepcopy(state.source_manifest),
                counts=dict(metric_series=len(rows), store_cluster_store=len(clusters), rule_config=len(rules),
                            data_update_log=session.execute(select(func.count()).select_from(DataUpdateLog)).scalar_one()))


def _frozen(session, state, *, include_cache=True):
    if state is None:
        from app.repository import DataSourceUnavailableError
        raise DataSourceUnavailableError("business version migration not ready")
    raw = _raw_inputs(session, state)
    caches = []
    if include_cache:
        for row in session.execute(select(VersionedReasoning).where(VersionedReasoning.scope_id == SCOPE_ID)).scalars():
            caches.append({column.name: deepcopy(getattr(row, column.name)) for column in VersionedReasoning.__table__.columns})
    return FrozenBusiness(raw, build_version(raw), caches)


def freeze_business_inputs(session, *, consume_row=None, check_deadline=None, admit_rows=None):
    if admit_rows:admit_rows(session,BusinessRevision,BusinessRevision.scope_id==SCOPE_ID)
    state=session.get(BusinessRevision,SCOPE_ID)
    if state is None:
        from app.repository import DataSourceUnavailableError
        raise DataSourceUnavailableError('business version migration not ready')
    raw=_raw_inputs(session,state,consume_row=consume_row,check_deadline=check_deadline,admit_rows=admit_rows)
    if check_deadline: check_deadline()
    return FrozenBusiness(raw,build_version(raw))


def business_write(method):
    """Wrap only business-input writers; Action/Wiki transactions stay independent."""
    method_signature = signature(method)
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        state = getattr(self, "_business_state", None)
        if state is None:
            with self.business_transaction() as tx:
                return wrapped(tx, *args, **kwargs)
        result = method(self, *args, **kwargs)
        state["dirty"] = True
        manifest = deepcopy(state["row"].source_manifest)
        mode = state["source_mode"] or "legacy_unknown"
        name = method.__name__
        if name in {"upsert_series", "replace_series"}:
            arguments = method_signature.bind(self, *args, **kwargs).arguments
            items = arguments["items"]
            keys = {it["metric_key"] for it in items}
            if name == "replace_series": keys.update(arguments["metric_keys"])
            for key in keys: manifest["metric:" + key] = mode
        elif name == "delete_all_series":
            manifest = {k: v for k, v in manifest.items() if not k.startswith("metric:")}
        elif "cluster" in name:
            manifest["cluster"] = mode
        elif "rules" in name:
            manifest["rules"] = mode
        else:
            manifest["event"] = mode
        state["row"].source_manifest = manifest
        return result
    return wrapped


class BusinessStore:
    @business_write
    def delete_all_cluster_stores(self):
        with self._session_ctx() as session:
            session.execute(delete(StoreClusterStore))
            self._commit(session)

    @contextmanager
    def business_transaction(self, source_mode=None, commit_guard=None, prepare_transaction=None):
        budget = guard_budget(commit_guard)
        if budget is not None: budget.check()
        db.require_business_ready(db.get_engine())
        if getattr(self, "_business_state", None) is not None:
            if budget is not None: prepare_budget_session(self._session, budget)
            if prepare_transaction is not None: prepare_transaction(self._session)
            yield self
            self._session.flush()
            if commit_guard is not None: commit_guard()
            return
        if source_mode not in {None, "sample", "uploaded"}:
            raise ValueError("invalid business source mode")
        with budget_scope(budget), self._session_ctx() as session:
            try:
                if budget is not None: prepare_budget_session(session, budget)
                if prepare_transaction is not None: prepare_transaction(session)
                if session.bind.dialect.name == "sqlite" and not session.in_transaction():
                    session.execute(text("BEGIN IMMEDIATE"))
                initialize_scope(session)
                row = session.execute(select(BusinessRevision).where(BusinessRevision.scope_id == SCOPE_ID).with_for_update()).scalar_one()
                tx = type(self)(session, transactional=True)
                tx._business_state = dict(row=row, dirty=False, source_mode=source_mode)
                yield tx
                if tx._business_state["dirty"]:
                    row.generation += 1
                    session.execute(delete(VersionedReasoning).where(VersionedReasoning.scope_id == SCOPE_ID))
                    session.execute(delete(InsightReasoning))
                session.flush()
                tx.committed_business_version = _frozen(session, row, include_cache=False).business_version
                if commit_guard is not None: commit_guard()
                self._commit(session)
            except SQLAlchemyError as exc:
                try: session.rollback()
                except Exception: pass
                if budget is not None: budget.check()
                from app.repository import DataSourceUnavailableError
                raise DataSourceUnavailableError("business transaction unavailable") from exc
            except Exception:
                try: session.rollback()
                except Exception: pass
                raise

    def read_business_inputs(self):
        db.require_business_ready(db.get_engine())
        state = getattr(self, "_business_state", None)
        if state is not None:
            return _frozen(self._session, state["row"])

        def read():
            # Even a Repository borrowed by Action gets its own short input read view.
            engine = db.get_engine()
            isolation = "REPEATABLE READ" if engine.dialect.name == "postgresql" else "SERIALIZABLE"
            with budget_connection(engine) as connection:
                connection=connection.execution_options(isolation_level=isolation)
                if engine.dialect.name == "sqlite": connection.exec_driver_sql("BEGIN")
                with Session(connection) as session:
                    row = session.get(BusinessRevision, SCOPE_ID)
                    return _frozen(session, row)
        return self._wrap(read)

    def import_dataset(self, items, event):
        from app.ingest import IngestCapacityError,MAX_DATASET_ROWS
        from app.evidence.contracts import build_snapshot,EvidenceError
        from app.query.contracts import ReadLimits
        from app.rag.identity import canonical
        if len(items)>MAX_DATASET_ROWS:
            raise IngestCapacityError('数据超过下游 10000 行处理上限，请拆分后导入')
        keys = sorted({it["metric_key"] for it in items})
        with self.business_transaction(source_mode="uploaded") as tx:
            session=tx._session
            count=session.scalar(select(func.count()).select_from(MetricSeries).where(MetricSeries.metric_key.not_in(keys)))
            count+=session.scalar(select(func.count()).select_from(StoreClusterStore))
            count+=session.scalar(select(func.count()).select_from(RuleConfig))
            if count+len(items)+2>ReadLimits().maxReadViewRows:
                raise IngestCapacityError('合并后的经营数据超过下游 10000 行上限，请拆分或减少数据后导入')
            tx.replace_series(keys, items)
            tx.upsert_data_update({**event, "rows_added": len(items), "total_rows": tx.count_rows("metric_series"), "metrics": keys})
            session.flush()
            # The outer transaction increments generation after this body. Its
            # final value participates in both the view and snapshot byte caps.
            generation=tx._business_state['row'].generation+int(tx._business_state['dirty'])
            size=0
            def consume(_table,row):
                nonlocal size
                if _table=='business_revision':row={**row,'generation':generation}
                size+=len(canonical(row).encode('utf-8'))
                if size>ReadLimits().maxReadViewBytes:
                    raise IngestCapacityError('合并后的经营数据超过下游 2MiB 上限，请减少数据后导入')
            raw=_raw_inputs(session,tx._business_state['row'],consume_row=consume)
            raw['generation']=generation
            candidate=FrozenBusiness(raw,build_version(raw))
            try:build_snapshot(candidate)
            except EvidenceError as exc:
                if exc.code!='snapshot_too_large':raise
                raise IngestCapacityError('数据生成的历史证据包超过 2MiB 上限，请减少数据后导入') from exc
        return tx.committed_business_version

    def commit_reasoning_if_current(self, version, insight_id, input_hash, semantics, provider, generated_at, *, commit_guard=None):
        with self.business_transaction(commit_guard=commit_guard) as tx:
            state = tx._business_state["row"]
            frozen = _frozen(tx._session, state, include_cache=False)
            current_version = frozen.business_version
            if current_version != version:
                return "discarded"
            from app.engine.engine import run_engine
            from app.reasoning.semantics import template_semantics
            result = run_engine(frozen, use_cache=False)
            insight = next((i for i in result["insights"] if i["id"] == insight_id), None)
            if insight is None or reasoning_input_hash(insight, result["snapshot"]) != input_hash:
                return "discarded"
            template = template_semantics(insight_id, result["snapshot"])
            if not isinstance(semantics, dict) or any(semantics.get(k, {}).get("value") != template[k]["value"] for k in ("causeA", "causeB")):
                raise ValueError("reasoning numeric values differ from current template")
            if not isinstance(semantics.get("next"), list) or not all(isinstance(v, str) for v in semantics["next"]):
                raise ValueError("invalid reasoning next steps")
            values = dict(cache_key=cache_key(version, insight_id, input_hash), scope_id=SCOPE_ID,
                          insight_type_id=insight_id, occurrence_id=occurrence_id(version, insight_id),
                          business_version=version, input_hash=input_hash, semantics=semantics,
                          provider=provider, generated_at=generated_at)
            statement = _insert(tx._session, VersionedReasoning).values(**values)
            if commit_guard is not None: commit_guard()
            tx._session.execute(statement.on_conflict_do_update(index_elements=["cache_key"], set_={k: v for k, v in values.items() if k != "cache_key"}))
        return "updated"
