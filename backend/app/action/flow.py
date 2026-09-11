"""V5-T3 行动状态机服务层：合法性唯一真源。

- step：pending|blocked → start → in_progress → done(带 note/result) / in_progress → blocked
- case：open → running（首次 start）→ waiting_verify（全步骤 done）→ resolved（verify）
- resolved 冻结一切推进；continue → running（人工/工具继续推进，不自动开新步）。
"""
from app.repository import Repository


class ActionFlowError(ValueError):
    """状态机非法迁移/档案不存在。"""


def _get(repo: Repository, case_id: str) -> dict:
    case = repo.get_action_case(case_id)
    if case is None:
        raise ActionFlowError(f"action case not found: {case_id}")
    if case["status"] == "resolved":
        raise ActionFlowError("action case already resolved; further transitions frozen")
    return case


def _step(case: dict, seq: int) -> dict:
    for st in case.get("steps", []):
        if st["seq"] == seq:
            return st
    raise ActionFlowError(f"action step not found: seq={seq}")


def _recompute_case_status(repo: Repository, case_id: str) -> str:
    """全 done → waiting_verify，否则 running（已 resolved 由上层冻结）。"""
    case = repo.get_action_case(case_id)
    statuses = [st["status"] for st in case["steps"]]
    next_status = "waiting_verify" if statuses and all(s == "done" for s in statuses) else "running"
    repo.set_action_case_status(case_id, next_status)
    return next_status


def start_step(repo: Repository, case_id: str, seq: int) -> dict:
    case = _get(repo, case_id)
    step = _step(case, seq)
    if step["status"] not in ("pending", "blocked"):
        raise ActionFlowError(f"step {seq} can only start from pending|blocked, got {step['status']}")
    repo.set_action_step_status(case_id, seq, "in_progress")
    repo.set_action_case_status(case_id, "running")
    return repo.get_action_case(case_id)


def done_step(repo: Repository, case_id: str, seq: int, note: str = "", result: str = "") -> dict:
    case = _get(repo, case_id)
    step = _step(case, seq)
    if step["status"] != "in_progress":
        raise ActionFlowError(f"step {seq} can only be done from in_progress, got {step['status']}")
    repo.set_action_step_status(case_id, seq, "done", note=note, result=result)
    _recompute_case_status(repo, case_id)
    return repo.get_action_case(case_id)


def block_step(repo: Repository, case_id: str, seq: int, note: str = "") -> dict:
    case = _get(repo, case_id)
    step = _step(case, seq)
    if step["status"] != "in_progress":
        raise ActionFlowError(f"step {seq} can only be blocked from in_progress, got {step['status']}")
    repo.set_action_step_status(case_id, seq, "blocked", note=note)
    repo.set_action_case_status(case_id, "running")
    return repo.get_action_case(case_id)


MAX_STEP_EXPERTS = 8


def set_step_experts(repo: Repository, case_id: str, seq: int, experts: list[str]) -> dict:
    """action-loop-timeline：整体设置某步负责专家（结构性校验 + resolved 冻结）。

    - 元素必须是 strip 后非空的字符串；同名校验去重保序；数量上限 MAX_STEP_EXPERTS。
    - **不**做专家池白名单校验：池属前端能力目录（design D6）；E1 专家注册表落地后再收紧。
    - 返回最新 case（与 start/done/blocked/verify 同形），调用方一次拿到权威状态。
    """
    if any(not isinstance(name, str) or not name.strip() for name in experts):
        raise ActionFlowError("experts must be non-empty strings")
    names = list(dict.fromkeys(name.strip() for name in experts))
    if len(names) > MAX_STEP_EXPERTS:
        raise ActionFlowError(f"too many experts: {len(names)} > {MAX_STEP_EXPERTS}")
    case = _get(repo, case_id)  # case 不存在 / resolved 冻结
    _step(case, seq)            # seq 存在性
    updated = repo.set_action_step_experts(case_id, seq, names)
    if updated is None:         # 理论上不可达（_step 已确认该 seq 存在）
        raise ActionFlowError(f"action step not found: seq={seq}")
    return repo.get_action_case(case_id) or case


def verify(repo: Repository, case_id: str, outcome: str, note: str = "") -> dict:
    if outcome not in ("resolved", "continue"):
        raise ActionFlowError(f"invalid verify outcome: {outcome}")
    case = repo.get_action_case(case_id)
    if case is None:
        raise ActionFlowError(f"action case not found: {case_id}")
    if case["status"] == "resolved":
        raise ActionFlowError("action case already resolved")
    if outcome == "resolved":
        statuses = [st["status"] for st in case["steps"]]
        if not statuses or not all(s == "done" for s in statuses):
            raise ActionFlowError("resolved requires all steps done (case should be waiting_verify)")
        if not note:
            raise ActionFlowError("resolved requires a note")
    repo.verify_action_case(case_id, outcome, note=note)
    return repo.get_action_case(case_id)
