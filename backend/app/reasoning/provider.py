"""推理 provider 协议与默认实现（T1，零行为变化）。

- ReasoningProvider：解释接口（未来可由 LLM 实现）。
- TemplateProvider：默认实现，输出与当前引擎模板语义完全一致（parity 测试保障）。
- resolve_provider()：由 DORA_REASONING_PROVIDER 选择；当前仅支持 template。
"""
import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ReasoningContext:
    """引擎给到解释层的上下文（判定结果 + 依据，均由引擎给定）。"""
    insight_id: str
    insight_type: str
    metric: str
    delta: str
    trigger: str
    factors: list[str]
    question: str
    snapshot: dict = field(default_factory=dict)


@dataclass
class ReasoningResult:
    """解释层输出。T1 仅携带与引擎模板一致的 semantics；T2/T3 扩展文案与来源标注。"""
    semantics: dict | None = None
    provider: str = "template"
    note: str = ""


class ReasoningProvider(Protocol):
    kind: str

    def explain(self, context: ReasoningContext) -> ReasoningResult:
        """根据引擎上下文生成解释文案。"""
        ...


class TemplateProvider:
    kind = "template"

    def explain(self, context: ReasoningContext) -> ReasoningResult:
        # semantics 由 reasoning 包提供（V3-T2 收编，不再依赖引擎私有函数）
        from app.reasoning.semantics import template_semantics
        semantics = None
        try:
            semantics = template_semantics(context.insight_id, context.snapshot) or {}
        except KeyError:  # 引擎无该 id 模板时保持空语义
            semantics = {}
        return ReasoningResult(
            semantics=semantics,
            provider=self.kind,
            note="模板解释（V3-T2，与引擎默认输出一致）",
        )


def resolve_provider(name: str | None = None) -> ReasoningProvider:
    """按配置解析 provider；未知值抛错，防止静默用错解释来源。"""
    chosen = (name or os.environ.get("DORA_REASONING_PROVIDER") or "template").strip().lower()
    if chosen == "template":
        return TemplateProvider()
    raise ValueError(f"暂不支持的 reasoning provider：{chosen}（当前可用 template）")
