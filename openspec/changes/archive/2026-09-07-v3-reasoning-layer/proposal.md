## Why

V3 规划（§3A/D022）把"解释文案"与"判定逻辑"解耦。V3-T1 先落抽象层地基：定义 provider 协议、以引擎模板为默认 provider、提供配置解析与 parity 测试——零行为变化、无 LLM 也可全绿。engine 的接线放到 T2（语义缓存）再发生。

## What Changes

- 新增后端包 `app/reasoning/`：
  - `provider.py`：`ReasoningContext` / `ReasoningResult` / `ReasoningProvider` 协议 / `TemplateProvider`（默认，产出与当前引擎模板一致）/ `resolve_provider()`（读 `DORA_REASONING_PROVIDER`，默认 template）。
- 新增 `tests/reasoning_check.py`：默认 provider 解析为 TemplateProvider；对当前引擎全部洞察做 **parity 断言**（TemplateProvider 输出 == 引擎既有 semantics）。
- 不改引擎行为、不加端点、不接 LLM（T2/T3）。

## Capabilities

<!-- 纯抽象层/重构，skip_specs: true -->

## Impact

- 后端：新增 `backend/app/reasoning/*`、`backend/tests/reasoning_check.py`、`.env.example` 提示变量。
- 验证：`tests/reasoning_check`、`tests.run_all`、build 均保持绿色（引擎结果逐字段不变）。
