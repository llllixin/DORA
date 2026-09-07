"""数据访问层：引擎从 Repository 读取原始数据与规则配置（默认 PostgreSQL）。"""
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app import db
from app.models import (
    DataUpdateLog,
    InsightReasoning,
    MetricSeries,
    RuleConfig,
    StoreClusterStore,
    WatchEvent,
    WatchTarget,
)

# watch 领域枚举（V4-T1）：契约早暴露，非法值在 Repository 层拒绝
WATCH_STATUSES = {"watching", "paused"}
WATCH_FREQUENCIES = {"on_update", "daily 09:00", "weekly"}
WATCH_EVENT_KINDS = {"change", "escalate"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _target_dict(row: WatchTarget) -> dict[str, Any]:
    return {
        "id": row.id, "text": row.raw_text, "intent": row.intent,
        "status": row.status, "frequency": row.frequency,
        "last_checked_at": row.last_checked_at, "last_event_at": row.last_event_at,
        "created_at": row.created_at,
    }


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

    def get_reasoning(self, insight_id: str) -> dict | None:
        def _do():
            with self._session_ctx() as s:
                row = s.execute(
                    select(InsightReasoning).where(InsightReasoning.insight_id == insight_id)
                ).scalars().first()
                if not row:
                    return None
                return {
                    "semantics": row.semantics,
                    "provider": row.provider,
                    "generated_at": row.generated_at,
                }
        return self._wrap(_do)

    def upsert_reasoning(self, insight_id: str, semantics: dict, provider: str, generated_at: str) -> None:
        def _do():
            with self._session_ctx() as s:
                existing = s.execute(
                    select(InsightReasoning).where(InsightReasoning.insight_id == insight_id)
                ).scalars().first()
                if existing:
                    existing.semantics = semantics
                    existing.provider = provider
                    existing.generated_at = generated_at
                else:
                    s.add(InsightReasoning(
                        insight_id=insight_id, semantics=semantics,
                        provider=provider, generated_at=generated_at,
                    ))
                s.commit()
        self._wrap(_do)

    def delete_all_reasoning(self) -> None:
        def _do():
            with self._session_ctx() as s:
                s.execute(delete(InsightReasoning))
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
            "insight_reasoning": InsightReasoning,
            "watch_target": WatchTarget,
            "watch_event": WatchEvent,
        }[table]

        def _do():
            with self._session_ctx() as s:
                return int(s.execute(select(func.count()).select_from(model)).scalar())
        return self._wrap(_do)

    # ---------- 持续关注：watch_target / watch_event（V4-T1） ----------
    def create_watch_target(
        self,
        text: str,
        intent: dict[str, Any] | None = None,
        status: str = "watching",
        frequency: str = "on_update",
    ) -> dict[str, Any]:
        """创建委托；校验 status/frequency 枚举，返回带 id 的完整记录。"""
        if status not in WATCH_STATUSES:
            raise ValueError(f"invalid watch status: {status}")
        if frequency not in WATCH_FREQUENCIES:
            raise ValueError(f"invalid watch frequency: {frequency}")
        now = _now_iso()
        target_id = f"w-{uuid4().hex[:12]}"

        def _do():
            with self._session_ctx() as s:
                s.add(WatchTarget(
                    id=target_id, raw_text=text, intent=intent or {},
                    status=status, frequency=frequency, created_at=now,
                ))
                s.commit()
        self._wrap(_do)
        return {
            "id": target_id, "text": text, "intent": intent or {},
            "status": status, "frequency": frequency,
            "last_checked_at": "", "last_event_at": "", "created_at": now,
        }

    def list_watch_targets(self) -> list[dict[str, Any]]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(
                    select(WatchTarget).order_by(WatchTarget.created_at.desc(), WatchTarget.id.desc())
                ).scalars().all()
                return [_target_dict(r) for r in rows]
        return self._wrap(_do)

    def get_watch_target(self, target_id: str) -> dict[str, Any] | None:
        def _do():
            with self._session_ctx() as s:
                row = s.get(WatchTarget, target_id)
                return _target_dict(row) if row else None
        return self._wrap(_do)

    def set_watch_status(self, target_id: str, status: str) -> dict[str, Any] | None:
        """暂停/恢复；目标不存在返回 None（幂等语义由调用方处理）。"""
        if status not in WATCH_STATUSES:
            raise ValueError(f"invalid watch status: {status}")

        def _do():
            with self._session_ctx() as s:
                row = s.get(WatchTarget, target_id)
                if row is None:
                    return None
                row.status = status
                s.commit()
                return _target_dict(row)
        return self._wrap(_do)

    def delete_watch_target(self, target_id: str) -> bool:
        """删除委托并级联清理其全部事件；目标不存在返回 False（幂等）。"""

        def _do():
            with self._session_ctx() as s:
                row = s.get(WatchTarget, target_id)
                if row is None:
                    return False
                s.execute(delete(WatchEvent).where(WatchEvent.target_id == target_id))
                s.delete(row)
                s.commit()
                return True
        return self._wrap(_do)

    def delete_all_watch_targets(self) -> None:
        """清空全部委托与事件（出厂重置/T3 接线备用）。"""

        def _do():
            with self._session_ctx() as s:
                s.execute(delete(WatchEvent))
                s.execute(delete(WatchTarget))
                s.commit()
        self._wrap(_do)

    def add_watch_event(
        self,
        target_id: str,
        kind: str,
        summary: str,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录一次命中事件；kind 校验，target 不存在抛 ValueError。"""
        if kind not in WATCH_EVENT_KINDS:
            raise ValueError(f"invalid watch event kind: {kind}")
        now = _now_iso()

        def _do():
            with self._session_ctx() as s:
                if s.get(WatchTarget, target_id) is None:
                    raise ValueError(f"watch target not found: {target_id}")
                ev = WatchEvent(
                    target_id=target_id, triggered_at=now, kind=kind,
                    summary=summary, values=values or {},
                )
                s.add(ev)
                row = s.get(WatchTarget, target_id)
                row.last_event_at = now
                s.commit()
                return {"id": ev.id, "target_id": target_id, "triggered_at": now,
                        "kind": kind, "summary": summary, "values": values or {}}
        return self._wrap(_do)

    def list_watch_events(self, target_id: str) -> list[dict[str, Any]]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(
                    select(WatchEvent).where(WatchEvent.target_id == target_id).order_by(WatchEvent.id)
                ).scalars().all()
                return [
                    {"id": r.id, "target_id": r.target_id, "triggered_at": r.triggered_at,
                     "kind": r.kind, "summary": r.summary, "values": r.values}
                    for r in rows
                ]
        return self._wrap(_do)

    def touch_watch_target(self, target_id: str, checked_at: str) -> bool:
        """更新 last_checked_at（评估完成后调用）；目标不存在返回 False。"""

        def _do():
            with self._session_ctx() as s:
                row = s.get(WatchTarget, target_id)
                if row is None:
                    return False
                row.last_checked_at = checked_at
                s.commit()
                return True
        return self._wrap(_do)

    def delete_all_watch_events(self) -> None:
        """清空全部命中事件（保留委托；出厂重置时旧数据引用失效）。"""

        def _do():
            with self._session_ctx() as s:
                s.execute(delete(WatchEvent))
                s.commit()
        self._wrap(_do)


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

