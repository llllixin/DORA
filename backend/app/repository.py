"""数据访问层：引擎从 Repository 读取原始数据与规则配置（默认 PostgreSQL）。"""
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app import db
from app.models import (
    ActionCase,
    ActionStep,
    CaseLesson,
    DataUpdateLog,
    InsightReasoning,
    KnowledgeArchive,
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

# action 领域枚举（V5-T1）
ACTION_CASE_STATUSES = {"open", "running", "waiting_verify", "resolved"}
ACTION_STEP_STATUSES = {"pending", "in_progress", "done", "blocked"}


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
            "action_case": ActionCase,
            "action_step": ActionStep,
            "case_lesson": CaseLesson,
            "knowledge_archive": KnowledgeArchive,
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


    # ---------- 行动档案：action_case / action_step（V5-T1） ----------
    def create_action_case(
        self, case: dict[str, Any], steps: list[dict[str, Any]],
        status: str = "open",
    ) -> dict[str, Any]:
        """建案（单事务 case+首步集）；同 id 已存在抛 ValueError（幂等由调用方处理）。"""
        if status not in ACTION_CASE_STATUSES:
            raise ValueError(f"invalid action case status: {status}")
        now = _now_iso()
        case_id = case["id"]

        def _do():
            with self._session_ctx() as s:
                if s.get(ActionCase, case_id) is not None:
                    raise ValueError(f"action case exists: {case_id}")
                s.add(ActionCase(
                    id=case_id, kind=case.get("kind", "problem"),
                    tag=case.get("tag", ""), tag_cls=case.get("tag_cls", "red"),
                    case_title=case.get("case_title", ""), code=case.get("code", ""),
                    source=case.get("source", ""), status=status,
                    orchestration=case.get("orchestration") or {},
                    archive=case.get("archive", ""), created_at=now, updated_at=now,
                ))
                _insert_steps(s, case_id, steps)
                s.commit()
        self._wrap(_do)
        return self.get_action_case(case_id) or {}

    def upsert_seed_case(self, case: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        """seed 迁移用幂等 upsert：同事务重建 case+steps，不翻倍。"""
        now = _now_iso()
        case_id = case["id"]

        def _do():
            with self._session_ctx() as s:
                row = s.get(ActionCase, case_id)
                if row is None:
                    s.add(ActionCase(
                        id=case_id, kind=case.get("kind", "problem"),
                        tag=case.get("tag", ""), tag_cls=case.get("tag_cls", "red"),
                        case_title=case.get("case_title", ""), code=case.get("code", ""),
                        source=case.get("source", ""), status=case.get("status", "running"),
                        orchestration=case.get("orchestration") or {},
                        archive=case.get("archive", ""), created_at=now, updated_at=now,
                    ))
                else:
                    if row.status == "resolved":
                        # 补充①（knowledge-lifecycle）：seed 不得倒退 resolved 案——
                        # 已 resolved 档案保留其历史/知识/经验，跳过覆盖。
                        return
                    row.kind = case.get("kind", row.kind)
                    row.tag = case.get("tag", row.tag)
                    row.tag_cls = case.get("tag_cls", row.tag_cls)
                    row.case_title = case.get("case_title", row.case_title)
                    row.code = case.get("code", row.code)
                    row.source = case.get("source", row.source)
                    row.status = case.get("status", row.status)
                    row.orchestration = case.get("orchestration") or row.orchestration
                    row.archive = case.get("archive", row.archive)
                    row.updated_at = now
                s.execute(delete(ActionStep).where(ActionStep.case_id == case_id))
                _insert_steps(s, case_id, steps)
                s.commit()
        self._wrap(_do)

    def list_action_cases(self) -> list[dict[str, Any]]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(
                    select(ActionCase).order_by(ActionCase.kind, ActionCase.code)
                ).scalars().all()
                return [_action_case_dict(r) for r in rows]
        return self._wrap(_do)

    def get_action_case(self, case_id: str) -> dict[str, Any] | None:
        def _do():
            with self._session_ctx() as s:
                row = s.get(ActionCase, case_id)
                if row is None:
                    return None
                steps = s.execute(
                    select(ActionStep).where(ActionStep.case_id == case_id).order_by(ActionStep.seq)
                ).scalars().all()
                return {**_action_case_dict(row), "steps": [_action_step_dict(x) for x in steps]}
        return self._wrap(_do)

    def set_action_step_status(
        self, case_id: str, seq: int, status: str,
        note: str | None = None, result: str | None = None,
    ) -> dict[str, Any] | None:
        """置步骤状态；done 自动写 finished_at；case/step 不存在返回 None。"""
        if status not in ACTION_STEP_STATUSES:
            raise ValueError(f"invalid action step status: {status}")
        now = _now_iso()

        def _do():
            with self._session_ctx() as s:
                step = s.execute(
                    select(ActionStep).where(
                        ActionStep.case_id == case_id, ActionStep.seq == seq)
                ).scalars().first()
                if step is None:
                    return None
                step.status = status
                if note is not None:
                    step.note = note
                if result is not None:
                    step.result = result
                if status == "done" and not step.finished_at:
                    step.finished_at = now
                case = s.get(ActionCase, case_id)
                if case is not None:
                    case.updated_at = now
                s.commit()
                return _action_step_dict(step)
        return self._wrap(_do)

    def verify_action_case(self, case_id: str, outcome: str, note: str = "") -> dict[str, Any] | None:
        """验证归档：resolved → case resolved；continue → case running（D031-3，只改档案态）。

        note 追加进 archive（形成验证记录，不改引擎判定/reasonSource）。
        A2（knowledge-lifecycle）：outcome=resolved 时，置态 + archive 追加 + 知识自动入库
        在同一事务内完成（消除"已 resolved 但知识缺失"窗口）；知识写入按 (entry_type, source_id) 幂等。
        """
        if outcome not in ("resolved", "continue"):
            raise ValueError(f"invalid verify outcome: {outcome}")

        def _do():
            with self._session_ctx() as s:
                row = s.get(ActionCase, case_id)
                if row is None:
                    return None
                now = _now_iso()
                row.status = "resolved" if outcome == "resolved" else "running"
                row.updated_at = now
                if note:
                    row.archive = f"{row.archive}\n[{now}] {outcome}: {note}"
                if outcome == "resolved":
                    exists = s.execute(
                        select(KnowledgeArchive).where(
                            KnowledgeArchive.entry_type == row.kind,
                            KnowledgeArchive.source_id == case_id)
                    ).scalars().first()
                    if exists is None:
                        s.add(KnowledgeArchive(
                            entry_type=row.kind, source_id=case_id, code=row.code,
                            title=row.case_title, content=row.archive, note=note,
                            created_at=now))
                s.commit()
                return _action_case_dict(row)
        return self._wrap(_do)

    def set_action_case_status(self, case_id: str, status: str) -> dict[str, Any] | None:
        """直接置档案状态（状态机服务层推导用；不做迁移校验）。"""
        if status not in ACTION_CASE_STATUSES:
            raise ValueError(f"invalid action case status: {status}")

        def _do():
            with self._session_ctx() as s:
                row = s.get(ActionCase, case_id)
                if row is None:
                    return None
                row.status = status
                row.updated_at = _now_iso()
                s.commit()
                return _action_case_dict(row)
        return self._wrap(_do)

    def delete_action_case(self, case_id: str) -> bool:
        """删除档案并级联清理步骤/经验/知识（A1 同事务）；不存在返回 False（幂等）。"""

        def _do():
            with self._session_ctx() as s:
                if s.get(ActionCase, case_id) is None:
                    return False
                s.execute(delete(ActionStep).where(ActionStep.case_id == case_id))
                s.execute(delete(CaseLesson).where(CaseLesson.case_id == case_id))
                s.execute(delete(KnowledgeArchive).where(KnowledgeArchive.source_id == case_id))
                s.delete(s.get(ActionCase, case_id))
                s.commit()
                return True
        return self._wrap(_do)

    def delete_all_action_cases(self) -> None:
        def _do():
            with self._session_ctx() as s:
                s.execute(delete(CaseLesson))
                s.execute(delete(KnowledgeArchive))
                s.execute(delete(ActionStep))
                s.execute(delete(ActionCase))
                s.commit()
        self._wrap(_do)

    # ---------- 行动经验沉淀：case_lesson（迭代 36） ----------
    def create_case_lesson(self, case_id: str, note: str) -> dict | None:
        """resolved 档案 → 经验沉淀（case_id 幂等）。case 不存在返回 None。"""

        def _do():
            with self._session_ctx() as s:
                existing = s.get(CaseLesson, case_id)
                if existing is not None:
                    return {"created": False, "lesson": _case_lesson_dict(existing)}
                row = s.get(ActionCase, case_id)
                if row is None:
                    return None
                lesson = CaseLesson(
                    case_id=case_id, code=row.code, kind=row.kind,
                    title=row.case_title, archive=row.archive,
                    resolution=note, created_at=_now_iso(),
                )
                s.add(lesson)
                # 统一知识库同步写入（类型 lesson，同事务）
                s.add(KnowledgeArchive(
                    entry_type="lesson", source_id=case_id, code=row.code,
                    title=row.case_title, content=row.archive, note=note,
                    created_at=lesson.created_at))
                s.commit()
                return {"created": True, "lesson": _case_lesson_dict(lesson)}
        return self._wrap(_do)

    def list_case_lessons(self) -> list[dict]:
        def _do():
            with self._session_ctx() as s:
                rows = s.execute(
                    select(CaseLesson).order_by(CaseLesson.created_at.desc(), CaseLesson.case_id.desc())
                ).scalars().all()
                return [_case_lesson_dict(r) for r in rows]
        return self._wrap(_do)

    def delete_case_lesson(self, case_id: str) -> bool:
        """删除经验（测试自清等）；不存在返回 False。"""

        def _do():
            with self._session_ctx() as s:
                row = s.get(CaseLesson, case_id)
                if row is None:
                    return False
                s.delete(row)
                s.commit()
                return True
        return self._wrap(_do)

    # ---------- 统一知识/归档库：knowledge_archive（迭代 38） ----------
    def add_knowledge(self, entry_type: str, source_id: str, code: str,
                      title: str, content: str, note: str = "") -> dict | None:
        """按类型写入知识（(entry_type, source_id) 唯一幂等）。重复返回既有（created=False）。"""
        now = _now_iso()

        def _do():
            with self._session_ctx() as s:
                existing = s.execute(
                    select(KnowledgeArchive).where(
                        KnowledgeArchive.entry_type == entry_type,
                        KnowledgeArchive.source_id == source_id)
                ).scalars().first()
                if existing is not None:
                    return {"created": False, "entry": _knowledge_dict(existing)}
                row = KnowledgeArchive(
                    entry_type=entry_type, source_id=source_id, code=code,
                    title=title, content=content, note=note, created_at=now)
                s.add(row)
                s.commit()
                return {"created": True, "entry": _knowledge_dict(row)}
        return self._wrap(_do)

    def list_knowledge(self, entry_type: str | None = None) -> list[dict]:
        def _do():
            with self._session_ctx() as s:
                q = select(KnowledgeArchive)
                if entry_type:
                    q = q.where(KnowledgeArchive.entry_type == entry_type)
                rows = s.execute(q.order_by(KnowledgeArchive.created_at.desc(), KnowledgeArchive.id.desc())).scalars().all()
                return [_knowledge_dict(r) for r in rows]
        return self._wrap(_do)

    def delete_knowledge_by_source(self, entry_type: str, source_id: str) -> bool:
        """删除知识（测试自清等）。"""

        def _do():
            with self._session_ctx() as s:
                row = s.execute(
                    select(KnowledgeArchive).where(
                        KnowledgeArchive.entry_type == entry_type,
                        KnowledgeArchive.source_id == source_id)
                ).scalars().first()
                if row is None:
                    return False
                s.delete(row)
                s.commit()
                return True
        return self._wrap(_do)


def _insert_steps(s, case_id: str, steps: list[dict[str, Any]]) -> None:
    for i, st in enumerate(steps):
        s.add(ActionStep(
            case_id=case_id, seq=st.get("seq", i), title=st.get("title", ""),
            desc=st.get("desc", ""), evidence=st.get("evidence", ""), why=st.get("why", ""),
            status=st.get("status", "pending"), note=st.get("note", ""),
            result=st.get("result", ""), finished_at=st.get("finished_at", ""),
        ))


def _action_case_dict(row: ActionCase) -> dict[str, Any]:
    return {
        "id": row.id, "kind": row.kind, "tag": row.tag, "tag_cls": row.tag_cls,
        "case_title": row.case_title, "code": row.code, "source": row.source,
        "status": row.status, "orchestration": row.orchestration,
        "archive": row.archive, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _action_step_dict(row: ActionStep) -> dict[str, Any]:
    return {
        "id": row.id, "case_id": row.case_id, "seq": row.seq,
        "title": row.title, "desc": row.desc, "evidence": row.evidence,
        "why": row.why, "status": row.status, "note": row.note,
        "result": row.result, "finished_at": row.finished_at,
    }


def _case_lesson_dict(row: CaseLesson) -> dict[str, Any]:
    return {
        "case_id": row.case_id, "code": row.code, "kind": row.kind,
        "title": row.title, "archive": row.archive, "resolution": row.resolution,
        "created_at": row.created_at,
    }


def _knowledge_dict(row: KnowledgeArchive) -> dict[str, Any]:
    return {
        "id": row.id, "entry_type": row.entry_type, "source_id": row.source_id,
        "code": row.code, "title": row.title, "content": row.content,
        "note": row.note, "created_at": row.created_at,
    }


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

