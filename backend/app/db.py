"""数据库连接（默认 PostgreSQL；DATABASE_URL 可切环境，本地可用 backend/.env）。"""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql+psycopg://dora:dora@localhost:5432/dora"

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


# A3（knowledge-lifecycle）：archive 相关列扩 TEXT。幂等 ALTER（PG 方言，重复执行 no-op）；
# create_all 不会改已有列类型，必须在 init 时补 DDL。
_TEXT_ALTERS: list[tuple[str, str]] = [
    ("action_case", "archive"),
    ("case_lesson", "archive"),
    ("case_lesson", "resolution"),
    ("knowledge_archive", "content"),
    ("knowledge_archive", "note"),
]


def init_db():
    from app.models import Base
    engine = get_engine()
    Base.metadata.create_all(engine)
    if engine.dialect.name != "postgresql":
        return  # 方言守卫：非 PG（如未来 sqlite/mock）不执行 ALTER ... TYPE TEXT
    for table, column in _TEXT_ALTERS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TEXT"))
        except SQLAlchemyError as exc:
            # 幂等宽容：列已 TEXT/表缺失时打印并继续，不阻断建表与门禁
            print(f"[db.init_db] ALTER {table}.{column} skipped: {exc}")


def make_session():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()
