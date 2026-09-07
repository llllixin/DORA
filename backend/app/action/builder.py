"""V5-T2 Case 建档引擎：引擎判定的 problem/opportunity 洞察 → action_case + 步骤模板。

红线（D031-2）：只接受"当前引擎判定集内"的 problem/opportunity；change/watch escalate/伪造一律拒绝。
幂等：同洞察已有档案 → 返回既有（created=False）。
"""
import hashlib

from app.engine.engine import run_engine
from app.repository import Repository

CODE_PREFIX = {"problem": "PRB-", "opportunity": "UPC-"}
ORCH_DEFAULTS = {
    "problem": {"experts": ["经营分析专家", "财务专家"], "data": [],
                "expertDesc": "问题拆解与影响判断"},
    "opportunity": {"experts": ["经营增长专家", "商品专家"], "data": [],
                    "expertDesc": "增长来源拆解与复制验证"},
}
ARCHIVE_DEFAULTS = {
    "problem": "执行结果、证据链与验证结论都会回写到本档案。",
    "opportunity": "执行结果、增长贡献、试点结论与复制建议都会回写到本档案。",
}


def _is_engine_judged(insight: dict, engine_insights: list[dict]) -> bool:
    if insight.get("type") not in ("problem", "opportunity"):
        return False
    return any(
        x.get("id") == insight.get("id") and x.get("type") == insight.get("type")
        for x in engine_insights
    )


def _step(seq: int, title: str, desc: str, evidence: str, status: str, why: str = "") -> dict:
    return {"seq": seq, "title": title, "desc": desc, "evidence": evidence,
            "status": status, "why": why}


def _steps_for(insight: dict) -> list[dict]:
    problem = insight["type"] == "problem"
    kind_label = "问题" if problem else "机会"
    title = insight.get("title", "")
    metric_delta = f"{insight.get('metric', '')} · {insight.get('delta', '')}"
    factors = " / ".join(insight.get("factors") or []) or "待归因"
    if problem:
        return [
            _step(0, "发现问题", insight.get("desc", ""),
                  f"{metric_delta} · {insight.get('trigger', '')}", "done"),
            _step(1, "定位原因", f"围绕触发归因关键因素：{factors}，定位可干预原因。",
                  metric_delta, "in_progress", why=insight.get("question") or "定位哪个因素最可干预"),
            _step(2, "持续验证", "处理后持续观察该指标是否回到目标/基线。", f"{metric_delta} · 后续观察", "pending"),
            _step(3, "问题解决", "只有业务结果恢复后才结束本档案。", "结果快照 · 档案回写", "pending"),
        ]
    return [
        _step(0, "发现机会", insight.get("desc", ""),
              f"{metric_delta} · {insight.get('trigger', '')}", "done"),
        _step(1, "拆解来源", f"拆解增长贡献与共性动作：{factors}。",
              metric_delta, "in_progress", why=insight.get("question") or "拆解增长是否可复制"),
        _step(2, "小范围验证", "选相似对象做小范围试点，再评估是否放大。", "试点 · 相似对象", "pending"),
        _step(3, "复制推广", "试点通过后复制推广并结束本档案。", "复制结果 · 档案回写", "pending"),
    ]


def _case_for(insight: dict) -> dict:
    problem = insight["type"] == "problem"
    kind_label = "问题" if problem else "机会"
    code = f"{CODE_PREFIX[insight['type']]}{hashlib.sha1(insight['id'].encode()).hexdigest()[:4].upper()}"
    return {
        "id": insight["id"], "kind": insight["type"],
        "tag": insight.get("tag") or (kind_label if problem else "机会"),
        "tag_cls": "red" if problem else "green",
        "case_title": f"{kind_label}档案 · {insight.get('title', '')} · {code}",
        "code": code,
        "source": f"来源：{kind_label}洞察 · {insight.get('title', '')}",
        "orchestration": ORCH_DEFAULTS[insight["type"]],
        "archive": ARCHIVE_DEFAULTS[insight["type"]],
    }


def create_case_from_insight(repo: Repository, insight: dict) -> dict:
    """建档：仅引擎当前判定的 problem/opportunity；同洞察已有档案返回既有。"""
    existing = repo.get_action_case(insight["id"])
    if existing is not None:
        return {"case": existing, "created": False}
    engine_insights = run_engine(repo)["insights"]
    if not _is_engine_judged(insight, engine_insights):
        raise ValueError(f"只允许为引擎判定的 problem/opportunity 建档，收到：{insight.get('id')}/{insight.get('type')}")
    case = _case_for(insight)
    detail = repo.create_action_case(case, _steps_for(insight), status="open")
    return {"case": detail, "created": True}
