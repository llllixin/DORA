"""Normalize storage failures before service-level model fallback handling."""
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
from app.rag.contracts import RagIndexUnavailable


def storage_errors(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except SQLAlchemyError as exc:
            raise RagIndexUnavailable('data_source_unavailable') from exc
    return guarded
