"""LLM 解释 Provider（V3-T3）：OpenAI 兼容 chat/completions。

红线：只允许 LLM 改写"可读文案"，数值永远以引擎模板基线为准。
兜底（阶段 1）：单条超时 ≤10s（env DORA_LLM_TIMEOUT）；熔断开启不触网快速失败；
网络级降级（超时/URLError/5xx/429）计入熔断；本地配置/解析错误不计。
"""
import json
import os
import socket
import urllib.request
from urllib.error import HTTPError, URLError

from app.reasoning import policy
from app.reasoning.provider import ReasoningContext, ReasoningResult
from app.reasoning.semantics import template_semantics
from app.runtime.executor import managed_call, runtime_managed
from app.runtime.contracts import ProviderEnvelope, RuntimeFailure

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

    def __init__(self):
        self._frozen_config = (
            (os.environ.get("DORA_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
            os.environ.get("DORA_LLM_API_KEY") or "",
            os.environ.get("DORA_LLM_MODEL") or "gpt-4o-mini",
        )
        from app.business_version import reasoning_profile
        from app.runtime.budget import load_profile
        self.budget_profile = load_profile("reasoning-refresh", True)
        self._profile = reasoning_profile(self.kind, configuration=self._frozen_config, budget_profile=self.budget_profile)
    external = True
    supports_timeout = True
    supports_output_cap = True

    @property
    def model(self): return self._config()[2]

    @property
    def profile(self): return dict(self._profile)

    def _config(self):
        return self._frozen_config

    @runtime_managed
    def explain(self, context: ReasoningContext, *, run_context=None) -> ReasoningResult:
        base, key, model = self._config()
        if not key:
            raise RuntimeError("DORA_LLM_API_KEY not set (LLM provider unavailable)")
        if policy.breaker.is_open():
            raise RuntimeFailure('circuit_open')
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
            'max_tokens': self.budget_profile.maxOutputTokensPerCall,
        }
        def perform(attempt):
            if policy.breaker.is_open(): raise RuntimeFailure('circuit_open')
            if policy.timeout_secs() <= 0: raise RuntimeFailure('configuration_error')
            attempt.timeout = min(attempt.timeout, policy.timeout_secs())
            try:
                data = attempt.post_json(f'{base}/chat/completions', key, payload, 'chat-completions')
            except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
                if policy.is_degraded(exc): policy.breaker.record_failure()
                raise
            policy.breaker.record_success()
            content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
            merged = _merge_with_numeric_stability(template, _parse_json(content))
            return ProviderEnvelope(ReasoningResult(semantics=merged, provider=self.kind,
                note='LLM 解释（数值已锁定为引擎基线）'), attempt.usage, model, attempt.response_model, attempt.response_id)
        return managed_call('reasoning-refresh', run_context, 'reasoning', self, payload, perform,
                            output_tokens=self.budget_profile.maxOutputTokensPerCall)


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
