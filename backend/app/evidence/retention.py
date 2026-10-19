"""Retain evidence and append deletion events under the scope-first lock order."""
from contextlib import contextmanager
from sqlalchemy import select
from app import db
from app.models import ActionCase,WatchTarget
from app.evidence.contracts import EvidenceError
from app.evidence.migrations import require_evidence_ready
from app.evidence.repository import EvidenceRepository


@contextmanager
def retention_transaction(repo):
    require_evidence_ready(db.get_engine())
    if repo._transactional and getattr(repo,'_business_state',None) is None:raise EvidenceError('evidence_unavailable',503)
    with repo.business_transaction() as tx:yield tx


def delete_source_captured(repo,*,kind,public_id):
    model=ActionCase if kind=='action_case' else WatchTarget
    with retention_transaction(repo) as tx:
        row=tx._session.scalar(select(model).where(model.id==public_id).with_for_update().execution_options(populate_existing=True))
        if row is None:return False
        EvidenceRepository(tx._session).record_source_deleted(kind,row.history_instance_id)
        method=tx._delete_action_case_in_transaction if kind=='action_case' else tx._delete_watch_target_in_transaction
        return method(public_id)


def delete_all_sources_captured(repo,*,kind):
    model=ActionCase if kind=='action_case' else WatchTarget
    with retention_transaction(repo) as tx:
        rows=tx._session.scalars(select(model).order_by(model.id).with_for_update()).all()
        for row in rows:delete_source_captured(tx,kind=kind,public_id=row.id)


def clear_watch_events_captured(repo):
    with retention_transaction(repo) as tx:
        tx._session.scalars(select(WatchTarget).order_by(WatchTarget.id).with_for_update()).all()
        tx._delete_all_watch_events_in_transaction()
