"""数据库连接（默认 PostgreSQL；DATABASE_URL 可切环境，本地可用 backend/.env）。"""
import os
from weakref import WeakKeyDictionary

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql+psycopg://dora:dora@localhost:5432/dora"

_engine = None
_business_readiness = WeakKeyDictionary()


def require_business_ready(engine):
    if _business_readiness.get(engine) is False:
        from app.repository import DataSourceUnavailableError
        raise DataSourceUnavailableError("critical business migration not ready")


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

# action-loop-timeline：新增列同样走「create_all 之外补 DDL」的幂等模式（PG 方言，
# `IF NOT EXISTS` 对新建表 no-op），旧行读回缺省 `[]` → 界面空态（无数据回填、无破坏性变更）。
_COLUMN_ADDS: list[tuple[str, str]] = [
    ("action_step", "experts JSON NOT NULL DEFAULT '[]'"),
]


def init_db():
    engine = get_engine()
    _business_readiness[engine] = False
    _initialize_database(engine)
    _business_readiness[engine] = True
    from app.rag.migration import init_rag_index
    init_rag_index(engine)


def ensure_initialized():
    """Seed may initialize a new DB; ready request paths do not toggle readiness."""
    if _business_readiness.get(get_engine()) is not True:init_db()


def _initialize_database(engine):
    from app.models import Base
    from app.evidence.migrations import TABLES,init_evidence
    from app.graph.migrations import init_graph
    history_tables={m.__tablename__ for m in TABLES}
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if not table.name.startswith(('rag_', 'graph_')) and table.name not in history_tables])
    # Required version capability: failures propagate to business reads as 503.
    from app.business_store import init_business_revision
    init_business_revision(engine)
    try: init_evidence(engine)
    except Exception as exc: print(f'[db.init_db] evidence capability unavailable: {exc}')
    try: init_graph(engine)
    except Exception as exc: print(f'[db.init_db] graph capability unavailable: {exc}')
    _backfill_watch_escalation()
    if engine.dialect.name != "postgresql":
        return  # 方言守卫：非 PG（如未来 sqlite/mock）不执行 ALTER ... TYPE TEXT
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE data_update_log DROP CONSTRAINT IF EXISTS uq_data_update"))
        conn.execute(text("ALTER TABLE data_update_log ALTER COLUMN updated_at TYPE VARCHAR(64)"))
    _migrate_action_case_origin(engine)
    for table, column in _TEXT_ALTERS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TEXT"))
        except SQLAlchemyError as exc:
            # 幂等宽容：列已 TEXT/表缺失时打印并继续，不阻断建表与门禁
            print(f"[db.init_db] ALTER {table}.{column} skipped: {exc}")
    for table, definition in _COLUMN_ADDS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {definition}"))
        except SQLAlchemyError as exc:
            # 幂等宽容：列已存在/表缺失时打印并继续（create_all 对旧库不补列，故需此 DDL）
            print(f"[db.init_db] ADD {table} {definition} skipped: {exc}")


def _backfill_watch_escalation() -> None:
    """watch-escalate-handoff 幂等数据迁移：已升级但状态仍 watching 的委托 → escalated。

    放在 init_db 内（启动即生效）；局部 import 避免 db ↔ repository 循环依赖；
    失败只打印不阻断（与下面的幂等 DDL 同策略：迁移不该让服务起不来）。
    """
    try:
        from app.repository import Repository
        moved = Repository().backfill_watch_escalation()
        if moved:
            print(f"[db.init_db] watch escalation backfill: {moved} target(s) → escalated")
    except Exception as exc:  # noqa: BLE001 - 数据源不可用/无表时跳过（幂等，下次启动再试）
        print(f"[db.init_db] watch escalation backfill skipped: {exc}")


def _migrate_action_case_origin(engine) -> None:
    """action-demo-separation 一次性来源标记迁移（幂等，靠「列是否存在」触发）。

    为什么不用 `_COLUMN_ADDS` 盲加列：只 `ADD COLUMN ... DEFAULT 'engine'` 会把旧库里 5 份
    种子演示档案默认成 `engine`，演示标记**永久丢失**（无其它字段可回溯哪些行是种子建立的）。
    故：列不存在 → 建列（缺省 engine）+ 把静态演示集 id 的行标 `demo`；列已存在 → no-op
    （新库由 create_all 建列 + seed 直接写 `demo`，此处自然跳过）。
    """
    from sqlalchemy import bindparam

    def _backfill(conn) -> int:
        ids = list(_static_action_ids())
        if not ids:
            return 0
        stmt = text("UPDATE action_case SET origin='demo' WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        return conn.execute(stmt, {"ids": ids}).rowcount

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='action_case' AND column_name='origin'"
                )
            ).first()
            if exists:
                return  # 幂等：列已存在（新库 / 已迁移库）→ 不动任何行（不覆盖已认领档案）
            conn.execute(
                text(
                    "ALTER TABLE action_case ADD COLUMN origin VARCHAR(16) "
                    "NOT NULL DEFAULT 'engine'"
                )
            )
            moved = _backfill(conn)
            print(f"[db.init_db] action_case.origin added; {moved} seed row(s) → demo")
    except Exception as exc:  # noqa: BLE001 - 数据源不可用/表缺失时只打印（幂等，下次启动再试）
        print(f"[db.init_db] action_case.origin migration skipped: {exc}")


def _static_action_ids() -> list[str]:
    """静态演示集 id（迁移 backfill 白名单）——局部 import 避免 db ↔ data 常量在启动期强耦合。"""
    try:
        from app.data import ACTIONS
        return list(ACTIONS.keys())
    except Exception as exc:  # noqa: BLE001 - 演示集缺失不应阻断建表
        print(f"[db.init_db] static action ids unavailable: {exc}")
        return []


def make_session():
    from app.db_budget import current_budget, BudgetSession
    budget = current_budget()
    if budget is not None: return BudgetSession(get_engine(), budget)
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()
