from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from datetime import datetime, timezone
import json
import threading

from app.data import ACTIONS, EVIDENCE, INSIGHTS
from app.schemas import (
    ActionCaseModel,
    EvidenceModel,
    InsightSummary,
    Pulse,
    WatchCreateRequest,
    WatchParseRequest,
    WatchStatusRequest,
)
from app.ingest import (
    IngestValidationError,
    items_from_mapping,
    parse_dataset,
    preview_rows,
    read_rows,
)
from app.reasoning.cache import refresh as reasoning_refresh
from app.reasoning.provider import resolve_provider
from app.repository import Repository
from app.seed import run_seed
from app.watch.evaluator import evaluate_all as watch_evaluate_all
from app.watch.evaluator import evaluate_one as watch_evaluate_one
from app.watch.parser import parse_watch_text

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok", "service": "dora-api"}


@router.get("/pulse", response_model=Pulse)
def pulse():
    return Pulse(**run_engine()["pulse"])


@router.get("/insights")
def list_insights(type: str = Query("problem", pattern="^(problem|opportunity|change)$")):
    return [i for i in run_engine()["insights"] if i["type"] == type]


@router.get("/insights/{insight_id}")
def get_insight(insight_id: str):
    for item in run_engine()["insights"]:
        if item["id"] == insight_id:
            return {
                **_to_summary(item).model_dump(),
                "route": "watch" if item["type"] == "change" else "action",
                "evidenceId": insight_id,
                "trigger": item["trigger"],
                "factors": item["factors"],
                "evidence": item["evidence"],
                "semantics": item["semantics"],
            }
    for items in INSIGHTS.values():  # 静态兜底：历史 id（如 o2 / c2）仍可读
        for item in items:
            if item["id"] == insight_id:
                return {
                    **item,
                    "route": "watch" if item["type"] == "change" else "action",
                    "evidenceId": insight_id,
                }
    raise HTTPException(status_code=404, detail="insight not found")


@router.get("/evidence/{evidence_id}", response_model=EvidenceModel)
def get_evidence(evidence_id: str):
    item = engine_evidence(evidence_id) or EVIDENCE.get(evidence_id)
    if not item:
        raise HTTPException(status_code=404, detail="evidence not found")
    return EvidenceModel(**item)


@router.get("/actions", response_model=list[ActionCaseModel])
def list_actions():
    return [ActionCaseModel(**item) for item in ACTIONS.values()]


@router.get("/actions/{action_id}", response_model=ActionCaseModel)
def get_action(action_id: str):
    item = ACTIONS.get(action_id)
    if not item:
        raise HTTPException(status_code=404, detail="action not found")
    return ActionCaseModel(**item)


@router.post("/actions/{action_id}/execute")
def execute_action(action_id: str):
    if action_id not in ACTIONS:
        raise HTTPException(status_code=404, detail="action not found")
    return {
        "ok": True,
        "actionId": action_id,
        "status": "running",
        "message": "执行任务已发起，结果将回写问题档案；Dora 将继续验证。",
    }


def _watch_card(repo: Repository, target: dict) -> dict:
    """委托 → WatchItem 兼容卡片（Pulse/Topbar 消费 watchItems 零改动升级）。"""
    intent = target.get("intent") or {}
    label = intent.get("label") or target["id"]
    dimension = intent.get("dimension", "")
    cond = intent.get("condition") or {}
    cond_txt = {
        "streak_below": f"连续 {cond.get('days', 1)} 天下降",
        "streak_above": f"连续 {cond.get('days', 1)} 天上涨",
        "below": f"跌破 {cond.get('ref')}",
        "above": f"超过 {cond.get('ref')}",
    }.get(cond.get("type"), "关注变化")
    freq = target.get("frequency") or "on_update"
    freq_txt = {"on_update": "数据更新时", "daily 09:00": "每日 09:00", "weekly": "每周"}.get(freq, freq)
    events = repo.list_watch_events(target["id"])
    last = events[-1] if events else None
    if target["status"] == "paused":
        value, color = "已暂停", "blue"
    elif last and last["kind"] == "escalate":
        value, color = "已升级", "red"
    elif last and last["kind"] == "change":
        value, color = "有变化", "blue"
    else:
        value, color = "观察中", "green"
    logic = f"{cond_txt}（{freq_txt}）"
    if target.get("last_event_at"):
        logic += f" · 最近命中 {target['last_event_at'][5:16].replace('T', ' ')}"
    return {
        "id": target["id"],
        "name": label,
        "value": value,
        "color": color,
        "logic": logic,
        "source": f"{label} · {dimension or '全量'}",
        "status": target["status"],
        "frequency": freq,
        "lastEventAt": target.get("last_event_at") or (last["triggered_at"] if last else ""),
    }


@router.get("/watch")
def list_watch():
    repo = Repository()
    return [_watch_card(repo, t) for t in repo.list_watch_targets()]


from app.engine.engine import engine_evidence, run_engine

MODEL_FIELDS = set(InsightSummary.model_fields)


def _to_summary(item: dict) -> InsightSummary:
    return InsightSummary(**{k: item[k] for k in MODEL_FIELDS})


@router.get("/engine/run")
def engine_run():
    return run_engine()


@router.get("/engine/pulse")
def engine_pulse():
    return run_engine()["pulse"]


@router.get("/engine/insights")
def engine_insights():
    return run_engine()["insights"]


MAX_UPLOAD = 10 * 1024 * 1024  # 10MB


def _watch_after_data_write(repo: Repository) -> None:
    """数据写入成功后即时评估 on_update 委托（V4-T3）。

    辅助逻辑：失败只告警，不影响上传主流程（事件可由下次触发/调度补）。
    """
    try:
        stats = watch_evaluate_all(repo)
        if stats["checked"]:
            print(f"[watch] on-update evaluate: {stats}")
    except Exception as exc:
        print(f"[watch] on-update evaluate skipped: {exc}")


@router.post("/datasets/sample")
def upload_sample():
    counts = run_seed()
    # 出厂重置：数据回到出厂 → 旧命中事件失效（清事件、保留委托），再即时评估
    repo = Repository()
    repo.delete_all_reasoning()
    repo.delete_all_watch_events()
    _watch_after_data_write(repo)
    return {"ok": True, "counts": counts}


@router.get("/datasets/current")
def current_dataset():
    repo = Repository()
    latest = repo.get_latest_update() or {}
    counts = {t: repo.count_rows(t) for t in ("metric_series", "store_cluster_store", "data_update_log", "rule_config")}
    return {"latest": latest, "counts": counts}


@router.post("/datasets")
async def upload_dataset(file: UploadFile = File(...)):
    name = file.filename or "upload.csv"
    if not (name.lower().endswith(".csv") or name.lower().endswith(".xlsx")):
        raise HTTPException(status_code=400, detail="仅支持 .csv / .xlsx 文件")
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件超过 10MB 上限")
    try:
        items = parse_dataset(name, content)
    except IngestValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not items:
        raise HTTPException(status_code=400, detail="文件内容为空")
    keys = sorted({it["metric_key"] for it in items})
    repo = Repository()
    repo.delete_all_reasoning()  # 数据变更 → 旧解释失效
    repo.replace_series(keys, items)
    now = datetime.now().strftime("%H:%M")
    repo.upsert_data_update({
        "updated_at": now,
        "rows_added": len(items),
        "total_rows": repo.count_rows("metric_series"),
        "metrics": keys,
    })
    _watch_after_data_write(repo)
    return {"ok": True, "name": name, "rows": len(items), "affectedMetrics": keys, "updated": now}


def _check_upload(name: str, content: bytes) -> None:
    if not (name.lower().endswith(".csv") or name.lower().endswith(".xlsx")):
        raise HTTPException(status_code=400, detail="仅支持 .csv / .xlsx 文件")
    if len(content) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件超过 10MB 上限")


@router.post("/datasets/preview")
async def preview_dataset(file: UploadFile = File(...)):
    name = file.filename or "preview.csv"
    content = await file.read()
    _check_upload(name, content)
    try:
        data = preview_rows(content, name)
    except IngestValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "name": name, **data}


@router.post("/datasets/mapped")
async def mapped_dataset(file: UploadFile = File(...), mapping: str = Form(...)):
    try:
        mp = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="mapping 必须是合法 JSON")
    if not isinstance(mp, dict):
        raise HTTPException(status_code=400, detail="mapping 必须是对象")
    name = file.filename or "mapped.csv"
    content = await file.read()
    _check_upload(name, content)
    try:
        raw = read_rows(content, name)
        items = items_from_mapping(raw, mp)
    except IngestValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    keys = sorted({it["metric_key"] for it in items})
    repo = Repository()
    repo.delete_all_reasoning()  # 数据变更 → 旧解释失效
    repo.replace_series(keys, items)
    now = datetime.now().strftime("%H:%M")
    repo.upsert_data_update({
        "updated_at": now,
        "rows_added": len(items),
        "total_rows": repo.count_rows("metric_series"),
        "metrics": keys,
    })
    _watch_after_data_write(repo)
    return {"ok": True, "name": name, "rows": len(items), "affectedMetrics": keys, "updated": now}

@router.post("/reason/refresh")
def reason_refresh():
    """批量刷新（阶段 1 单飞）：并发重复请求合并为一次执行，后到者复用首个结果。"""
    with _refresh_cond:
        if _refresh_state["running"]:
            while _refresh_state["running"]:
                _refresh_cond.wait()
            if _refresh_state["error"] is not None:
                raise _refresh_state["error"]
            return _refresh_state["result"]
        _refresh_state["running"] = True
        _refresh_state["result"] = None
        _refresh_state["error"] = None
    try:
        out = _compute_refresh_once()
    except Exception as exc:
        with _refresh_cond:
            _refresh_state["error"] = exc
            _refresh_state["running"] = False
            _refresh_cond.notify_all()
        raise
    with _refresh_cond:
        _refresh_state["result"] = out
        _refresh_state["running"] = False
        _refresh_state["error"] = None
        _refresh_cond.notify_all()
    return out


_refresh_cond = threading.Condition()
_refresh_state = {"running": False, "result": None, "error": None}


def _compute_refresh_once() -> dict:
    repo = Repository()
    provider = resolve_provider()
    res = run_engine(repo)
    if not res["insights"]:
        return {"ok": True, "updated": [], "fallback": [], "provider": provider.kind}
    out = reasoning_refresh(repo, res["insights"], res["snapshot"], provider)
    return {"ok": True, **out}


@router.post("/watch/parse")
def watch_parse(req: WatchParseRequest):
    """委托语句解析（V4-T2）：纯文本词典解析，不触 DB；结果供前端确认后创建。"""
    return parse_watch_text(req.text)


@router.post("/watch")
def create_watch(req: WatchCreateRequest):
    """创建委托：parse（unsupported→400）→ 落库 → 即时评估一次（V4-T3/T4）。"""
    parsed = parse_watch_text(req.text)
    if not parsed["ok"]:
        reason = (parsed["unsupported"] or [{}])[0].get("reason", "无法解析该委托")
        raise HTTPException(status_code=400, detail=reason)
    intent = parsed["intent"]
    freq = req.frequency or intent.get("frequency") or "on_update"
    repo = Repository()
    target = repo.create_watch_target(req.text, intent, status="watching", frequency=freq)
    watch_evaluate_all(repo)
    return {"ok": True, "target": _watch_card(repo, repo.get_watch_target(target["id"]))}


@router.get("/watch/{watch_id}")
def get_watch(watch_id: str):
    repo = Repository()
    target = repo.get_watch_target(watch_id)
    if target is None:
        raise HTTPException(status_code=404, detail="watch not found")
    return {"ok": True, "target": target, "events": repo.list_watch_events(watch_id)}


@router.patch("/watch/{watch_id}")
def update_watch_status(watch_id: str, req: WatchStatusRequest):
    repo = Repository()
    target = repo.set_watch_status(watch_id, req.status)
    if target is None:
        raise HTTPException(status_code=404, detail="watch not found")
    return {"ok": True, "target": _watch_card(repo, target)}


@router.delete("/watch/{watch_id}")
def delete_watch(watch_id: str):
    repo = Repository()
    deleted = repo.delete_watch_target(watch_id)  # 幂等：不存在也返回 ok
    return {"ok": True, "deleted": deleted}


@router.post("/watch/{watch_id}/check")
def check_watch(watch_id: str):
    """手动立即评估一次（验收/测试用）。"""
    repo = Repository()
    target = repo.get_watch_target(watch_id)
    if target is None:
        raise HTTPException(status_code=404, detail="watch not found")
    out = watch_evaluate_one(repo, target)
    repo.touch_watch_target(watch_id, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return {"ok": True, **out}

