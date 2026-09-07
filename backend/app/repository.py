"""数据访问层：引擎从 Repository 读取原始数据与规则配置（默认 PostgreSQL）。"""
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app import db
from app.models import DataUpdateLog, MetricSeries, RuleConfig, StoreClusterStore


class DataSourceUnavailableError(Exception):
    """数据源不可用（数据库离线等），上层应映射为 503。"""


class Repository:
    """读/写接口；每次操作短会话。写接口供 seed 使用，读接口供引擎计算。"""

    def __init__(self, session=None):
        self._session = session

    def _session_ctx(self):
        if self._session is not None:
            return _Ctx(self._session)
        return _Ctx(db.make_session())

    def _wrap(self, fn):
        try:
            return fn()
        except (OperationalError, SQLAlchemyError) as exc:  # 数据库连接失败
            raise DataSourceUnavailableError(f"data source unavailable: {exc}") from exc

    # ---------- 读取：时间序列 ----------
    def get_series(self, metric_key: str) -> list[dict[str, Any]]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(
                    select(MetricSeries)
                    .where(MetricSeries.metric_key == metric_key)
                    .order_by(MetricSeries.id)
                ).scalars().all()
                return [
                    {"label": r.label, "value": r.value, "dimension": r.dimension, "unit": r.unit}
                    for r in rows
                ]
        return self._wrap(_do)

    # ---------- 读取：门店集群 / 更新事件 / 规则 ----------
    def get_cluster_stores(self) -> list[dict[str, Any]]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(select(StoreClusterStore)).scalars().all()
                return [{"store": r.store, "region": r.region, "aov": r.aov} for r in rows]
        return self._wrap(_do)

    def get_latest_update(self) -> dict[str, Any] | None:
        def _do():
            with self._session_ctx() as s:
                row = s.execute(
                    select(DataUpdateLog).order_by(DataUpdateLog.id.desc()).limit(1)
                ).scalars().first()
                if not row:
                    return None
                return {
                    "updated": row.updated_at,
                    "rows_added": row.rows_added,
                    "total_rows": row.total_rows,
                    "metrics": row.metrics,
                }
        return self._wrap(_do)

    def get_rules(self) -> dict[str, Any]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(select(RuleConfig)).scalars().all()
                out: dict[str, Any] = {}
                for r in rows:
                    out[r.key] = _cast(r.value, r.value_type)
                return out
        return self._wrap(_do)

    # ---------- 写入：种子 upsert ----------
    def upsert_series(self, items: list[dict[str, Any]]) -> None:
        def _do():
            with self._session_ctx() as s:
                for it in items:
                    existing = s.execute(
                        select(MetricSeries).where(
                            MetricSeries.metric_key == it["metric_key"],
                            MetricSeries.label == it["label"],
                            MetricSeries.dimension == it.get("dimension", ""),
                        )
                    ).scalar_one_or_none()
                    if existing:
                        existing.value = it["value"]
                        existing.unit = it.get("unit", "")
                    else:
                        s.add(MetricSeries(**it))
                s.commit()
        self._wrap(_do)

    def delete_all_updates(self) -> None:
        """清空数据更新日志（样例/重置用，恢复出厂事件）。"""

        def _do():
            with self._session_ctx() as s:
                s.execute(delete(DataUpdateLog))
                s.commit()
        self._wrap(_do)

    def delete_all_series(self) -> None:
        """清空全部时间序列（样例/重置用，保证还原到出厂状态）。"""

        def _do():
            with self._session_ctx() as s:
                s.execute(delete(MetricSeries))
                s.commit()
        self._wrap(_do)

    def replace_series(self, metric_keys: list[str], items: list[dict[str, Any]]) -> None:
        """同事务替换指定指标 key 的系列（上传=换数据源语义）。"""

        def _do():
            with self._session_ctx() as s:
                if metric_keys:
                    s.execute(delete(MetricSeries).where(MetricSeries.metric_key.in_(metric_keys)))
                for it in items:
                    if it.get("metric_key") in metric_keys:
                        s.add(MetricSeries(**it))
                s.commit()
        self._wrap(_do)

    def upsert_cluster_stores(self, items: list[dict[str, Any]]) -> None:
        def _do():
            with self._session_ctx() as s:
                for it in items:
                    existing = s.execute(
                        select(StoreClusterStore).where(StoreClusterStore.store == it["store"])
                    ).scalar_one_or_none()
                    if existing:
                        existing.region = it["region"]
                        existing.aov = it["aov"]
                    else:
                        s.add(StoreClusterStore(**it))
                s.commit()
        self._wrap(_do)

    def upsert_data_update(self, item: dict[str, Any]) -> None:
        def _do():
            with self._session_ctx() as s:
                existing = s.execute(
                    select(DataUpdateLog).where(DataUpdateLog.updated_at == item["updated_at"])
                ).scalar_one_or_none()
                if existing:
                    existing.rows_added = item["rows_added"]
                    existing.total_rows = item["total_rows"]
                    existing.metrics = item["metrics"]
                else:
                    s.add(DataUpdateLog(**item))
                s.commit()
        self._wrap(_do)

    def upsert_rules(self, items: list[dict[str, Any]]) -> None:
        def _do():
            with self._session_ctx() as s:
                for it in items:
                    existing = s.get(RuleConfig, it["key"])
                    if existing:
                        existing.value = it["value"]
                        existing.value_type = it["value_type"]
                    else:
                        s.add(RuleConfig(**it))
                s.commit()
        self._wrap(_do)

    def count_rows(self, table: str) -> int:
        from sqlalchemy import func
        model = {
            "metric_series": MetricSeries,
            "store_cluster_store": StoreClusterStore,
            "data_update_log": DataUpdateLog,
            "rule_config": RuleConfig,
        }[table]

        def _do():
            with self._session_ctx() as s:
                return int(s.execute(select(func.count()).select_from(model)).scalar())
        return self._wrap(_do)


class _Ctx:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        self.session.close()
        return False


def _cast(value: str, value_type: str):
    if value_type == "float":
        return float(value)
    if value_type == "int":
        return int(value)
    if value_type == "bool":
        return value.lower() == "true"
    return value

