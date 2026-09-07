## Context

见 proposal.md。T1/T2 已备好协议、模板 provider、缓存与合并标注；T3 接入 LLM 并补失效。依赖：无额外 pip（HTTP 用标准库 urllib）。

## Goals / Non-Goals

**Goals:** LLMProvider（OpenAI 兼容）+ refresh 端点 + 无 key fallback + 数值稳定策略 + 数据写入即失效。

**Non-Goals:** Dora Chat SSE；工具调用/多步推理；前端（T4）；prompt 调参产线优化（T5 金样本再调）。

## Decisions

- **协议复用**：LLMProvider 实现现有 `explain(context)`；内部先算引擎模板语义作"数值事实基线"，LLM 只提供可读字段（causeA/B 的 name、next），再合并，**value 永远取模板基线** → 数值红线由代码保证而非只靠提示词。
- **JSON 解析**：要求模型输出 JSON object；容错剥 code fence 后再 json.loads；任一环节失败抛错（refresh 捕获 → fallback）。
- **无 key 行为**：`resolve_provider("llm")` 返回 LLMProvider；explain 时发现缺 key 抛 `RuntimeError` → refresh fallback（满足 spec 场景）。
- **失效策略（D024 退出）**：在数据写入路径（upload/mapped）与出厂重置（seed/sample）清空 `insight_reasoning`；不做行级指纹（当前洞察量小，全清足够）。
- refresh 端点默认对当前全部引擎洞察执行（可选 future 扩展 insightIds 白名单）。

## Risks / Trade-offs

- LLM 质量不稳定 → 以 JSON-only + 数值稳定策略兜底；文案可再生成（refresh 幂等）。
- 全清缓存粒度粗 → 数据集变化场景即失效，代价小（≤9 行）。
- 依赖外部服务延迟 → refresh 为同步批量；洞察量小可接受（后续可转异步/SSE，不进 T3）。
