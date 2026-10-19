"""Additive RAG schema readiness, independent of historical legacy-column reads."""
from weakref import WeakKeyDictionary
from sqlalchemy import inspect, text
from app.models import RagDocument, RagChunk, RagIndexProjection, RagIndexBatch, RagIndexState
from app.rag.contracts import RagIndexUnavailable

_ready = WeakKeyDictionary()
TABLES = (RagDocument, RagChunk, RagIndexProjection, RagIndexBatch, RagIndexState)


def init_rag_index(engine):
    _ready[engine] = False
    try:
        for model in TABLES: model.__table__.create(engine, checkfirst=True)
        with engine.begin() as conn:
            columns = {c['name'] for c in inspect(conn).get_columns('rag_document')}
            for name, kind in [('source_snapshot', 'JSON'), ('source_version_hash', 'VARCHAR(64)')]:
                if name not in columns:
                    conn.execute(text(f'ALTER TABLE rag_document ADD COLUMN {name} {kind}'))
        _ready[engine] = True
    except Exception as exc:
        raise RagIndexUnavailable('migration_not_ready') from exc


def require_rag_ready(engine, *, connection=None):
    if _ready.get(engine) is False: raise RagIndexUnavailable('migration_not_ready')
    try:
        schema = inspect(connection if connection is not None else engine)
        if not all(schema.has_table(m.__tablename__) for m in TABLES):
            raise RagIndexUnavailable('migration_not_ready')
        columns = {c['name'] for c in schema.get_columns('rag_document')}
        if not {'source_snapshot', 'source_version_hash'} <= columns:
            raise RagIndexUnavailable('migration_not_ready')
    except RagIndexUnavailable: raise
    except Exception as exc:
        if connection is not None:
            from sqlalchemy.exc import SQLAlchemyError
            if isinstance(exc,SQLAlchemyError): raise
        raise RagIndexUnavailable('migration_not_ready') from exc
