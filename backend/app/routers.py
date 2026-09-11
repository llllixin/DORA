from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
import json
import threading

from app.schemas import (
    ActionCreateRequest,
    AgentRunCreateRequest,
    AgentRunEventRequest,
    ArchiveLessonRequest,
    ChatRequest,
    EvidenceModel,
    InsightSummary,
    KnowledgeSearchRequest,
    Pulse,
    StepBodyRequest,
    StepExpertsRequest,
    VerifyRequest,
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
from app.action.builder import create_case_from_insight as action_build_case
from app.action import flow as action_flow

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
    raise HTTPException(status_code=404, detail="insight not found")  # 只认当前引擎判定（静态兜底已下线）


@router.get("/evidence/{evidence_id}", response_model=EvidenceModel)
def get_evidence(evidence_id: str):
    item = engine_evidence(evidence_id)  # 只认 Repository 生成证据（静态兜底已下线）
    if not item:
        raise HTTPException(status_code=404, detail="evidence not found")
    return EvidenceModel(**item)


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
        # watch-delegate-flow：委托生命周期回显（增量字段，复用上面已取到的 intent/last，不新增查询）
        "intent": intent,
        "lastCheckedAt": target.get("last_checked_at") or "",
        "lastEvent": (
            {"kind": last["kind"], "summary": last["summary"], "triggeredAt": last["triggered_at"]}
            if last else None
        ),
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


# ---------------------------------------------------------------------------
# V5-T3：/api/action/cases 真执行 REST（旧 /actions 静态端点保留到 T5）
# ---------------------------------------------------------------------------
def _action_detail_or_404(case_id: str):
    repo = Repository()
    case = repo.get_action_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="action case not found")
    return repo, case


@router.post("/action/cases")
def create_action_case(req: ActionCreateRequest):
    repo = Repository()
    engine_insights = run_engine(repo)["insights"]
    insight = next(
        (x for x in engine_insights if x["id"] == req.insight_id
         and x["type"] in ("problem", "opportunity")),
        None,
    )
    if insight is None:
        raise HTTPException(
            status_code=400,
            detail="只允许为当前引擎判定的 problem/opportunity 洞察建档",
        )
    try:
        out = action_build_case(repo, insight)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "created": out["created"], "case": out["case"]}


@router.get("/action/cases")
def list_action_cases():
    repo = Repository()
    return {"ok": True, "cases": repo.list_action_cases()}


@router.get("/action/cases/{case_id}")
def get_action_case(case_id: str):
    repo = Repository()
    case = repo.get_action_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="action case not found")
    return {"ok": True, "case": case}


def _step_action(case_id: str, seq: int, action: str, note: str = "", result: str = "") -> dict:
    repo, _ = _action_detail_or_404(case_id)
    try:
        if action == "start":
            updated = action_flow.start_step(repo, case_id, seq)
        elif action == "done":
            updated = action_flow.done_step(repo, case_id, seq, note=note, result=result)
        else:
            updated = action_flow.block_step(repo, case_id, seq, note=note)
    except action_flow.ActionFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "case": updated}


@router.post("/action/cases/{case_id}/steps/{seq}/start")
def action_step_start(case_id: str, seq: int):
    return _step_action(case_id, seq, "start")


@router.post("/action/cases/{case_id}/steps/{seq}/done")
def action_step_done(case_id: str, seq: int, body: StepBodyRequest):
    return _step_action(case_id, seq, "done", note=body.note, result=body.result)


@router.post("/action/cases/{case_id}/steps/{seq}/blocked")
def action_step_blocked(case_id: str, seq: int, body: StepBodyRequest):
    return _step_action(case_id, seq, "blocked", note=body.note)


@router.post("/action/cases/{case_id}/steps/{seq}/experts")
def action_step_experts(case_id: str, seq: int, body: StepExpertsRequest):
    """action-loop-timeline：整体设置该步负责专家（幂等；空列表=清除）。4xx=非法/resolved 冻结。"""
    repo, _ = _action_detail_or_404(case_id)
    try:
        updated = action_flow.set_step_experts(repo, case_id, seq, body.experts)
    except action_flow.ActionFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "case": updated}


@router.post("/action/cases/{case_id}/verify")
def action_verify(case_id: str, body: VerifyRequest):
    repo, _ = _action_detail_or_404(case_id)
    try:
        updated = action_flow.verify(repo, case_id, body.outcome, note=body.note)
    except action_flow.ActionFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "case": updated}


@router.post("/action/cases/{case_id}/archive-as-lesson")
def archive_as_lesson(case_id: str, body: ArchiveLessonRequest):
    """resolved 档案 → 经验沉淀（case_id 幂等）。非 resolved 或空结论拒绝。"""
    repo, case = _action_detail_or_404(case_id)
    if case["status"] != "resolved":
        raise HTTPException(status_code=400, detail="仅已归档（resolved）档案可沉淀经验")
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="沉淀经验必须填写结论（note）")
    out = repo.create_case_lesson(case_id, body.note.strip())
    if out is None:
        raise HTTPException(status_code=404, detail="action case not found")
    return {"ok": True, **out}


@router.get("/action/lessons")
def list_lessons():
    repo = Repository()
    return {"ok": True, "lessons": repo.list_case_lessons()}


@router.get("/knowledge")
def list_knowledge(type: str = Query("", pattern="^(|problem|opportunity|change|lesson)$")):
    """知识/归档库：按类型筛选；stats 始终返回各类型计数。"""
    repo = Repository()
    entries = repo.list_knowledge(type or None)
    all_entries = repo.list_knowledge() if type else entries
    stats: dict[str, int] = {}
    for et in ("problem", "opportunity", "change", "lesson"):
        stats[et] = sum(1 for e in all_entries if e["entry_type"] == et)
    return {"ok": True, "type": type or "all", "entries": entries, "stats": stats}


# ---------------------------------------------------------------------------
# Agent 工具层 / 检索 / 运行记录 / Dora Chat（agent-tool-layer，迭代 42）
# workflow.md §6.2 所需后端能力；Dify 侧配置见 docs/workflow.md §11
# ---------------------------------------------------------------------------
@router.get("/tools/query_metric")
def query_metric(metric_key: str, dimension: str = "", limit: int = 200):
    """只读工具：按口径读指标序列行；未知指标返回空数组（不 404、不编造）。"""
    repo = Repository()
    rows = repo.list_metric_series(metric_key, dimension or None, limit)
    return {"ok": True, "metric_key": metric_key, "dimension": dimension or None, "count": len(rows), "rows": rows}


@router.post("/knowledge/search")
def knowledge_search(req: KnowledgeSearchRequest):
    """RAG 检索：词法 top-k + 可回溯 references；空命中显式 empty=true。"""
    repo = Repository()
    hits = repo.search_knowledge(req.query, req.types or None, req.top_k)
    refs = [{"entry_type": h["entry_type"], "source_id": h["source_id"], "code": h["code"], "title": h["title"]}
            for h in hits]
    return {"ok": True, "query": req.query, "empty": not hits, "hits": hits, "references": refs}


@router.post("/agent/runs")
def create_agent_run(req: AgentRunCreateRequest):
    repo = Repository()
    run = repo.create_agent_run(req.trigger, req.input, req.events, req.output)
    return {"ok": True, "run": run}


@router.get("/agent/runs/{run_id}")
def get_agent_run(run_id: str):
    repo = Repository()
    run = repo.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return {"ok": True, "run": run}


@router.post("/agent/runs/{run_id}/events")
def append_agent_run_event(run_id: str, body: AgentRunEventRequest):
    repo = Repository()
    run = repo.append_agent_run_event(run_id, body.event)
    if run is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return {"ok": True, "run": run}


CHAT_INTENT_RULES = (
    ("why", ("为什么", "原因", "归因", "为何")),
    ("evidence", ("证据", "依据", "凭什么", "数据支持")),
    # insight-judgment-structure：后果一问（必须早于 handle——「不处理」也含「处理」子串）
    ("consequence", ("后果", "不处理", "会怎样", "会不会", "风险", "影响面")),
    ("opportunity", ("机会", "增长", "可复制")),
    ("delegate", ("关注", "提醒", "盯着", "跟踪")),
    ("handle", ("处理", "怎么办", "行动", "解决")),
)

# 严重等级文案（与引擎 severity.level 同源；只在答案文本里做中文映射）
SEVERITY_TEXT = {"high": "高", "medium": "中", "low": "低"}


def _chat_intent(question: str) -> str:
    for name, keys in CHAT_INTENT_RULES:
        if any(k in (question or "") for k in keys):
            return name
    return "what"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _compose_answer(intent: str, insight: dict | None, engine: dict, references: list[dict]) -> dict:
    """答案只由引擎字段 + 检索引用组装（数字锁：不引入引擎外数字/判定）。"""
    if insight is None:
        pulse = engine.get("pulse", {})
        return {"text": f"当前没有引擎判定的洞察；脉搏计数：{json.dumps(pulse, ensure_ascii=False)}",
                "references": references, "number_source": "engine"}
    sem = insight.get("semantics") or {}
    parts: list[str] = []
    if intent == "why":
        parts.append(f"「{insight.get('title', '')}」的判断来自引擎：{insight.get('desc', '')}")
        if sem.get("causeA"):
            parts.append(f"主要影响因素：{sem['causeA'].get('name', '')} {sem['causeA'].get('value', '')}".strip())
        if sem.get("causeB"):
            parts.append(f"进一步定位：{sem['causeB'].get('name', '')} {sem['causeB'].get('value', '')}".strip())
    elif intent == "evidence":
        parts.append(f"可回溯证据：指标 {insight.get('metric', '')}，变化 {insight.get('delta', '')}，来源 {insight.get('source', '')}。")
    elif intent == "consequence":
        # 两段前缀固定（前端按前缀归位到判断列段①/段③）；文本只由引擎字段组装（数字锁）
        sev = insight.get("severity") or {}
        cq = insight.get("consequence") or {}
        if sev:
            drivers = "、".join(f"{d.get('name', '')} {d.get('value', '')}".strip() for d in sev.get("drivers", []))
            parts.append(f"严重等级：{SEVERITY_TEXT.get(sev.get('level'), '')} {sev.get('score', '')} 分 · {drivers}")
        if cq:
            parts.append(f"可能后果：{cq.get('summary', '')}（{cq.get('condition', '')}；观察窗口 {cq.get('horizon', '')}）")
    elif intent == "opportunity":
        parts.append(f"这是 {insight.get('type', '')} 类洞察：{insight.get('desc', '')}")
    elif intent == "delegate":
        parts.append("建议到「持续关注」用一句话委托，例如：关注利润率，连续三天走弱时提醒我。")
    elif intent == "handle":
        parts.append("建议进入「行动回路」建档，按步骤执行并在完成后验证归档。")
    else:
        parts.append(f"{insight.get('title', '')}：{insight.get('desc', '')}")
    nxt = sem.get("next") or []
    if nxt:
        parts.append("下一步建议：" + "；".join(str(n) for n in nxt[:3]))
    if references:
        parts.append("可参考历史先例：" + "、".join(f"{r['title']}（{r['code']}）" for r in references))
    else:
        parts.append("历史知识库暂无同指标先例。")
    return {"text": "\n".join(parts), "references": references, "number_source": "engine"}


@router.post("/dora/chat")
def dora_chat(req: ChatRequest):
    """Dora Chat（SSE）：thought_step/tool_call/evidence/answer/done；落一条 agent_run（trigger=chat）。"""
    repo = Repository()
    intent = _chat_intent(req.question)
    engine = run_engine(repo)
    insights = engine.get("insights", [])
    insight = None
    if req.insight_id:
        insight = next((i for i in insights if i.get("id") == req.insight_id), None)
    if insight is None and insights:
        insight = insights[0]

    tool_calls = [{"tool": "get_engine_snapshot", "args": {"question": req.question}, "status": "ok"}]
    if insight is not None:
        ev = engine_evidence(insight["id"])
        tool_calls.append({"tool": "get_evidence", "args": {"id": insight["id"]}, "status": "ok" if ev else "empty"})

    query = f"{insight.get('title', '')} {insight.get('metric', '')}".strip() if insight else (req.question or "")
    hit_rows = repo.search_knowledge(query, ["lesson", "problem", "opportunity"], 3)
    references = [{"entry_type": h["entry_type"], "source_id": h["source_id"], "code": h["code"], "title": h["title"]}
                  for h in hit_rows]

    answer = _compose_answer(intent, insight, engine, references)
    events = [
        {"type": "thought_step", "data": {"node": "intent", "intent": intent, "text": f"识别意图：{intent}"}},
        {"type": "thought_step", "data": {"node": "engine_snapshot", "text": "读取引擎判定与证据"}},
        *[{"type": "tool_call", "data": tc} for tc in tool_calls],
        {"type": "evidence", "data": {"insight_id": insight.get("id") if insight else None, "refs": references}},
        {"type": "answer", "data": answer},
    ]
    run = repo.create_agent_run(
        trigger="chat",
        input_data={"question": req.question, "page": req.page, "workspace": req.workspace, "insight_id": req.insight_id},
        events=events,
        output={"answer": answer["text"], "intent": intent, "references": references},
    )

    def _gen():
        for ev in events:
            yield _sse(ev["type"], ev["data"])
        yield _sse("done", {"run_id": run["id"], "intent": intent})

    return StreamingResponse(_gen(), media_type="text/event-stream")

