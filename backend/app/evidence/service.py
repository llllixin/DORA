"""Scope-first capture transaction and immutable package persistence."""
from contextlib import contextmanager
from app.db_budget import budget_scope
from app import db
from app.business_store import freeze_business_inputs
from app.evidence.contracts import EvidenceError,build_snapshot
from app.evidence.deadline import CaptureDeadline
from app.evidence.migrations import require_evidence_ready
from app.evidence.repository import EvidenceRepository,now


@contextmanager
def capture_transaction(repo,*,deadline=None):
    deadline=deadline or CaptureDeadline();deadline.check()
    if repo._transactional and getattr(repo,'_business_state',None) is None:raise EvidenceError('evidence_unavailable',503)
    try:
        with budget_scope(deadline): require_evidence_ready(db.get_engine())
        deadline.check()
        with repo.business_transaction(prepare_transaction=deadline.prepare_session,commit_guard=deadline.check) as tx:
            deadline.prepare_session(tx._session)
            frozen=freeze_business_inputs(tx._session,check_deadline=deadline.check)
            yield tx,frozen,deadline
            tx._session.flush();deadline.check()
    except EvidenceError:raise
    except Exception as exc:
        from app.repository import DataSourceUnavailableError
        from sqlalchemy.exc import SQLAlchemyError
        if not isinstance(exc,(SQLAlchemyError,DataSourceUnavailableError)):raise
        chain=exc
        while chain:
            original=getattr(chain,'orig',None)
            if getattr(original,'sqlstate',None) in ('55P03','57014'):raise EvidenceError('evidence_capture_timeout',503) from exc
            chain=chain.__cause__
        raise EvidenceError('evidence_unavailable',503) from exc


def persist_capture(tx,frozen,deadline):
    deadline.prepare_session(tx._session);package=build_snapshot(frozen);deadline.check();store=EvidenceRepository(tx._session)
    snapshot=store.put_snapshot(package,captured_at=now())
    for insight in package['payload']['factInsights']:
        store.put_occurrence(dict(occurrenceId=insight['occurrenceId'],insightTypeId=insight['id'],
            factIdentity=package['factVersion'],judgment=insight))
    deadline.prepare_session(tx._session)
    return snapshot
