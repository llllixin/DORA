from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from datetime import datetime

from app.data import ACTIONS, EVIDENCE, INSIGHTS, WATCH
from app.schemas import ActionCaseModel, EvidenceModel, InsightSummary, Pulse, WatchItem
from app.ingest import IngestValidationError, parse_dataset
from app.repository import Repository
from app.seed import run_seed

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


@router.post("/datasets/sample")
def upload_sample():
    counts = run_seed()
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
    repo.replace_series(keys, items)
    now = datetime.now().strftime("%H:%M")
    repo.upsert_data_update({
        "updated_at": now,
        "rows_added": len(items),
        "total_rows": repo.count_rows("metric_series"),
        "metrics": keys,
    })
    return {"ok": True, "name": name, "rows": len(items), "affectedMetrics": keys, "updated": now}
