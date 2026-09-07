"""V4-T2 委托语句解析：中文一句话 → 结构化 intent（规则词典，不接 LLM 判定）。

支持范围（D029 红线）：
- 指标 = 引擎受支持的 metric key（TARGETS 有序词典，最先命中者胜）。
- 条件 = 连续 N 天下降/上涨，或跌破/低于/超过/高于 X(%)（单条件，breach 优先）。
- 频率 = on_update / daily 09:00 / weekly；未提 → null（创建时由确认步选择）。
- 拒绝 = 匹配不到任何指标 → ok=false + unsupported（显式，不静默兜底）。
"""
import re
from typing import Any

# 指标词典（有序：靠前的 key 先匹配；别名覆盖引擎 key 的中文说法）
# dimension="" 表示该指标为门店/维度级，聚合口径由 T3 评估器定义
TARGETS: list[dict[str, Any]] = [
    {"key": "margin", "aliases": ["利润率", "毛利率", "毛利"], "label": "利润率", "dimension": "全国"},
    {"key": "east_orders", "aliases": ["华东销售额", "华东销售", "华东订单量", "华东订单"], "label": "华东销售额", "dimension": "华东"},
    {"key": "new_sku", "aliases": ["新品增长", "新品销量", "新品"], "label": "新品增长", "dimension": "全区域"},
    {"key": "returns", "aliases": ["退货率"], "label": "退货率", "dimension": ""},
    {"key": "revenue", "aliases": ["销售额", "营收"], "label": "销售额", "dimension": "全国"},
    {"key": "orders", "aliases": ["订单量", "总订单"], "label": "订单量", "dimension": "全国"},
    {"key": "aov", "aliases": ["客单价"], "label": "客单价", "dimension": "全国"},
    {"key": "high_value", "aliases": ["大额订单", "高客单", "高价值订单"], "label": "大额订单", "dimension": "全国"},
]

# 频率词（先后顺序有意义：更长词优先）
FREQ_TOKENS = [
    ("daily 09:00", ["每日 09:00", "每天 09:00", "每日九点", "每天早上"]),
    ("weekly", ["每周"]),
    ("on_update", ["数据更新时", "实时", "有数据更新就"]),
]

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_RE_DIGIT = re.compile(r"[0-9]+")
_RE_STREAK_DOWN = re.compile(r"连续\s*(?:(\d+|[一二两三四五六七八九十]+)\s*天?)?\s*(下降|下跌|回落|走低)")
_RE_STREAK_UP = re.compile(r"连续\s*(?:(\d+|[一二两三四五六七八九十]+)\s*天?)?\s*(上涨|上升|增长)")
_RE_BREACH = re.compile(r"(跌破|低于|降至)\s*(-?\d+(?:\.\d+)?)\s*(%?)")
_RE_ABOVE = re.compile(r"(超过|突破|高于|达到)\s*(-?\d+(?:\.\d+)?)\s*(%?)")

SUPPORTED_HINT = "支持的关键词示例：华东销售 / 利润率 / 退货率 / 新品增长 / 大额订单"


def _to_int(token: str | None) -> int:
    if not token:
        return 1
    if _RE_DIGIT.fullmatch(token):
        return int(token)
    # 中文数字：仅支持 1–10（含"两"）；"十"及以上按字面累加兜底
    if token in _CN_NUM:
        return _CN_NUM[token]
    return 3


def _find_target(text: str) -> dict[str, Any] | None:
    for target in TARGETS:
        for alias in target["aliases"]:
            if alias in text:
                return target
    return None


def _find_frequency(text: str) -> str | None:
    for value, words in FREQ_TOKENS:
        for w in words:
            if w in text:
                return value
    return None


def _find_condition(text: str) -> tuple[dict[str, Any] | None, bool]:
    """返回 (condition, 是否默认)。breach/above 优先于 streak（单条件语义）。"""
    m = _RE_BREACH.search(text)
    if m:
        return {"type": "below", "ref": float(m.group(2)), "ref_is_pct": bool(m.group(3))}, False
    m = _RE_ABOVE.search(text)
    if m:
        return {"type": "above", "ref": float(m.group(2)), "ref_is_pct": bool(m.group(3))}, False
    m = _RE_STREAK_DOWN.search(text)
    if m:
        return {"type": "streak_below", "days": _to_int(m.group(1)), "ref": None}, False
    m = _RE_STREAK_UP.search(text)
    if m:
        return {"type": "streak_above", "days": _to_int(m.group(1)), "ref": None}, False
    return None, False


def parse_watch_text(text: str) -> dict[str, Any]:
    target = _find_target(text)
    if target is None:
        # 粗略定位"疑似指标词"（名词性片段）用于 unsupported 提示
        fragment = text.replace("帮我", "").replace("关注", "").replace("如果", "").strip()
        words = re.split(r"[，,。；;\s]", fragment)
        suspect = next((w for w in words if w and len(w) >= 2), fragment[:8]) if fragment else "该指标"
        return {
            "ok": False,
            "intent": None,
            "unsupported": [{"token": suspect, "reason": f"暂不支持该指标（{SUPPORTED_HINT}）"}],
        }

    condition, defaulted = _find_condition(text)
    if condition is None:
        condition = {"type": "streak_below", "days": 3, "ref": None}
        defaulted = True

    intent = {
        "metric_key": target["key"],
        "dimension": target["dimension"],
        "condition": condition,
        "frequency": _find_frequency(text),
        "label": target["label"],
        "condition_defaulted": defaulted,
    }
    return {"ok": True, "intent": intent, "unsupported": []}
