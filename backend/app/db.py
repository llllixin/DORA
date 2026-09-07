"""数据库连接（默认 PostgreSQL；DATABASE_URL 可切环境，本地可用 backend/.env）。"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql+psycopg://dora:dora@localhost:5432/dora"

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


def init_db():
    from app.models import Base
    Base.metadata.create_all(get_engine())


def make_session():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()
