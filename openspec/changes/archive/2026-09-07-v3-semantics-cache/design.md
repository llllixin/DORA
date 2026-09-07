## Context

见 proposal.md。T1 已就绪 provider 抽象（默认 TemplateProvider 与引擎 semantics parity）。T2 的目标是把语义接到"缓存管线"，并顺手收编 `_semantics`（D023 退出条件）。

## Goals / Non-Goals

**Goals:** insight_reasoning 持久化 + run_engine 合并缓存（回退模板） + 来源标注；semantics 生成逻辑归 reasoning 包。

**Non-Goals:** LLM Provider 与刷新 API（T3）；前端改动；改变 semantics 结构/判定逻辑。

## Decisions

- **缓存表**：`insight_reasoning(insight_id 唯一 PK 关联 id 字符串, semantics JSON, provider, generated_at ISO)`；Repository 提供 `get_reasoning/upsert_reasoning/count_rows`。
- **收编 semantics**：把引擎私有 `_semantics(iid, snap)` 逻辑原样迁移到 `app/reasoning/semantics.py::template_semantics`；引擎 `from app.reasoning.semantics import template_semantics as _semantics` 保留内部接口，零改动调用点；`TemplateProvider` 改用 reasoning 包（去掉对 engine 的延迟 import）。
- **合并位置在 run_engine**（一处收口，list/detail 天然生效）：产出 insights 后对每条 `get_reasoning(id)`；命中→覆盖 semantics + reasonSource/生成时间；未命中→保持模板语义并加 `reasonSource="template"`（不写缓存，保证无 key 时不膨胀 DB）。
- **refresh 助手**（cache.py）为测试/后续 T3 提供写入口：逐条 provider.explain 并 upsert；返回 updated/fallback。

## Risks / Trade-offs

- run_engine 每条多一次查询（N+1）→ 当前洞察 ≤9，可接受；后续批量优化再议。
- 缓存被陈旧数据污染的风险（数据集变更后旧解释仍在）→ T3/T5 提供"refresh"与失效策略（T5 金样本时按 snapshot 指纹清理，本期不实现，注明边界）。
