## Why

V3-T1 已建 ReasoningProvider 抽象层（模板默认、parity 全绿），但引擎尚未消费。V3-T2 把"语义"接入缓存管线：新增 `insight_reasoning` 持久化，`/api/insights` 合并缓存语义并标注来源；无缓存回退模板。同时按 D023 退出条件把引擎 `_semantics` 收编进 reasoning 包。

## What Changes

- 数据：新增 `insight_reasoning` 表（insight_id 唯一、semantics JSON、provider、generated_at）；Repository 增读写与计数。
- 收编：`template_semantics(insight_id, snapshot)` 移入 `app/reasoning/semantics.py`；引擎以别名 `_semantics` 保留兼容；`TemplateProvider` 改为从 reasoning 包读取（不再 import 引擎私有函数）。
- 刷新助手：`app/reasoning/cache.py::refresh(repo, insights, provider)` —— 逐条用 provider 生成并写入缓存（默认 template 内容与现状一致），返回 updated/fallback。
- 合并：`run_engine()` 产出洞察后按缓存合并语义并附加只读标注：`reasonSource:"llm"|"template"`、`generatedAt?:ISO`；无缓存时语义=模板并标 `reasonSource:"template"`（不写缓存，行为与 V2 等价）。
- 展示契约结构不变（semantics 字段形状不变），仅新增元信息字段。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `business-engine`: 洞察语义来源可切换为缓存/Provider，并在响应中携带 `reasonSource` 与 `generatedAt`；无缓存时以模板语义回退（结果与 V2 一致）。

## Impact

- 后端：`models.py`、`repository.py`、`app/reasoning/{semantics.py,cache.py,provider.py}`、`engine/engine.py`、`tests/reasoning_check.py`。
- 无前端改动（新字段为只读附加，Insight 类型不变）。
- 验证：`reasoning_check` 扩展（含 refresh→合并标注断言）、`tests/run_all` 全绿、`npm run build`。
