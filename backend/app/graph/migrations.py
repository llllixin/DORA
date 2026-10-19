"""Independent, additive graph readiness; GET never repairs schema."""
from weakref import WeakKeyDictionary
from sqlalchemy import inspect
from app.graph.models import GraphEntity,GraphRelation,GraphRelationEvidence,GraphBuildBatch,GraphBuildMember,GraphState
from app.graph.contracts import GraphError

TABLES=(GraphEntity,GraphRelation,GraphRelationEvidence,GraphBuildBatch,GraphBuildMember,GraphState)
_ready=WeakKeyDictionary()


def init_graph(engine):
    _ready[engine]=False
    try:
        with engine.begin() as connection:
            for model in TABLES:model.__table__.create(connection,checkfirst=True)
        _ready[engine]=True
    except Exception as exc:raise GraphError('graph_migration_unavailable') from exc


def require_graph_ready(engine):
    if _ready.get(engine) is False:raise GraphError('graph_migration_unavailable')
    from app.db_budget import budget_connection
    try:
        with budget_connection(engine) as connection:
            schema=inspect(connection)
            for model in TABLES:
                if not schema.has_table(model.__tablename__):raise GraphError('graph_not_ready')
                if not set(model.__table__.columns.keys()) <= {c['name'] for c in schema.get_columns(model.__tablename__)}:
                    raise GraphError('graph_migration_unavailable')
    except GraphError:raise
    except Exception as exc:
        from app.db_budget import current_budget
        budget=current_budget()
        if budget is not None: budget.check()
        raise GraphError('graph_migration_unavailable') from exc
