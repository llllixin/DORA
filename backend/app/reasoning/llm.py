"""LLM 解释 Provider（V3-T3）：OpenAI 兼容 chat/completions。

红线：只允许 LLM 改写"可读文案"，数值永远以引擎模板基线为准。
"""
import json
import os
import urllib.request

from app.reasoning.provider import ReasoningContext, ReasoningResult
from app.reasoning.semantics import template_semantics

SYSTEM_PROMPT = (
    "你是 Dora 经营驾驶舱的解释助手。你会收到一条由引擎判定产生的洞察及其事实。"
    "请用中文输出仅一个 JSON 对象，不得包含其它文字，格式："
    '{"causeA": {"name": "<主要因素名称>", "value": "<原样照抄>"}, '
    '"causeB": {"name": "<进一步定位名称>", "value": "<原样照抄>"}, '
    '"next": ["<下一步1>", ...3-5 条]}。'
    "约束：causeA/causeB 的 value 必须逐字照抄引擎提供的事实值，禁止改写任何数字、百分比、触发条件；"
    "只允许优化 name 与 next 的表述；不要编造事实。"
)

USER_TEMPLATE = "洞察事实（必须如实引用）：{facts}"


class LLMProvider:
    kind = "llm"

    def _config(self):
        base = (os.environ.get("DORA_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        key = os.environ.get("DORA_LLM_API_KEY") or ""
        model = os.environ.get("DORA_LLM_MODEL") or "gpt-4o-mini"
        return base, key, model

    def explain(self, context: ReasoningContext) -> ReasoningResult:
        base, key, model = self._config()
        if not key:
            raise RuntimeError("DORA_LLM_API_KEY not set (LLM provider unavailable)")
        template = template_semantics(context.insight_id, context.snapshot) or {}
        facts = {
            "insight_id": context.insight_id,
            "type": context.insight_type,
            "metric": context.metric,
            "delta": context.delta,
            "trigger": context.trigger,
            "factors": context.factors,
            "question": context.question,
            "causeA": template.get("causeA"),
            "causeB": template.get("causeB"),
        }
        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(facts=json.dumps(facts, ensure_ascii=False))},
            ],
        }
        url = f"{base}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        llm = _parse_json(content)
        merged = _merge_with_numeric_stability(template, llm)
        return ReasoningResult(
            semantics=merged,
            provider=self.kind,
            note="LLM 解释（数值已锁定为引擎基线）",
        )


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("LLM 输出必须是 JSON 对象")
    return obj


def _merge_with_numeric_stability(base: dict, llm: dict) -> dict:
    """把 LLM 的可读字段合入引擎基线；value 一律取基线（红线）。"""
    out: dict = {}
    for key in ("causeA", "causeB"):
        if not isinstance(base.get(key), dict):
            continue
        name = base[key].get("name")
        if isinstance(llm.get(key), dict) and isinstance(llm[key].get("name"), str) and llm[key]["name"].strip():
            name = llm[key]["name"].strip()[:60]
        out[key] = {"name": name, "value": base[key].get("value")}
    nexts = llm.get("next")
    if isinstance(nexts, list) and 2 <= len(nexts) <= 6 and all(isinstance(x, str) and x.strip() for x in nexts):
        out["next"] = [x.strip()[:120] for x in nexts]
    elif isinstance(base.get("next"), list):
        out["next"] = base["next"]
    return out
