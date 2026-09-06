from fastapi import APIRouter, HTTPException, Query
from app.data import ACTIONS, EVIDENCE, INSIGHTS, PULSE, WATCH
from app.schemas import ActionCaseModel, EvidenceModel, InsightSummary, Pulse, WatchItem

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok", "service": "dora-api"}


@router.get("/pulse", response_model=Pulse)
def pulse():
    return Pulse(**PULSE)


@router.get("/insights", response_model=list[InsightSummary])
def list_insights(type: str = Query("problem", pattern="^(problem|opportunity|change)$")):
    return [InsightSummary(**item) for item in INSIGHTS.get(type, [])]


@router.get("/insights/{insight_id}")
def get_insight(insight_id: str):
    for items in INSIGHTS.values():
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
    item = EVIDENCE.get(evidence_id)
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
