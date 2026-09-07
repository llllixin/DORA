from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from datetime import datetime
import json

from app.data import ACTIONS, EVIDENCE, INSIGHTS, WATCH
from app.schemas import ActionCaseModel, EvidenceModel, InsightSummary, Pulse, WatchItem, WatchParseRequest
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


@router.get("/watch", response_model=list[WatchItem])
def list_watch():
    return [WatchItem(**item) for item in WATCH]


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
        from app.watch.evaluator import evaluate_all as watch_evaluate_all
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

