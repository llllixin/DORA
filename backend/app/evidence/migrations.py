"""Additive historical schema; readiness never silently creates history on GET."""
from weakref import WeakKeyDictionary
from contextlib import nullcontext
from sqlalchemy import inspect,text
from app.models import EvidenceSnapshot,InsightOccurrence,EvidenceBinding,ActionOccurrenceLink,ActionVerification,EvidenceSourceEvent
from app.evidence.contracts import EvidenceError

TABLES=(EvidenceSnapshot,InsightOccurrence,EvidenceBinding,ActionOccurrenceLink,ActionVerification,EvidenceSourceEvent)
COLUMNS={'action_case':'history_instance_id','watch_target':'history_instance_id','watch_event':'history_event_id'}
_ready=WeakKeyDictionary()


def init_evidence(engine):
    _ready[engine]=False
    try:
        with engine.begin() as conn:
            for model in TABLES:model.__table__.create(conn,checkfirst=True)
            for table,column in COLUMNS.items():
                columns={r['name'] for r in inspect(conn).get_columns(table)}
                if column not in columns:conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} VARCHAR(32)'))
        _ready[engine]=True
    except Exception as exc:raise EvidenceError('evidence_unavailable',503) from exc


def require_evidence_ready(engine, connection=None):
    if _ready.get(engine) is False:raise EvidenceError('evidence_unavailable',503)
    from app.db_budget import budget_connection
    try:
        with (nullcontext(connection) if connection is not None else budget_connection(engine)) as connection:
            schema=inspect(connection)
            if not all(schema.has_table(m.__tablename__) for m in TABLES):raise EvidenceError('evidence_unavailable',503)
            for table,column in COLUMNS.items():
                if column not in {r['name'] for r in schema.get_columns(table)}:raise EvidenceError('evidence_unavailable',503)
    except EvidenceError:raise
    except Exception as exc:
        from app.db_budget import current_budget
        budget=current_budget()
        if budget is not None: budget.check()
        raise EvidenceError('evidence_unavailable',503) from exc
