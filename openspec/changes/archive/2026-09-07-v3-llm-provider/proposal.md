## Why

V3-T1/T2 已完成抽象层与语义缓存（默认 template）。T3 接上真正的 LLM 解释（OpenAI 兼容）并暴露刷新入口，同时兑现 D024 退出条件：任何数据写入/出厂重置后使语义缓存失效，避免旧解释被命中。

## What Changes

- `LLMProvider`（`app/reasoning/llm.py`）：OpenAI 兼容 chat/completions；env `DORA_LLM_BASE_URL/API_KEY/MODEL`；system prompt 中文并要求 JSON；**数值稳定策略**：causeA/causeB 的 value 一律以引擎模板值为准（LLM 只可改写 name 与 next），next 经结构校验，任何异常抛错（走 refresh fallback）。
- `resolve_provider` 支持 `llm`（未配 key 时 explain 抛错 → refresh 把该条列入 fallback）。
- 新增端点 `POST /api/reason/refresh`：空 body 对当前全部引擎洞察执行 provider 刷新，返回 `{ok, updated, fallback, provider}`；幂等。
- **缓存失效**：数据写入（`POST /api/datasets`、`/datasets/mapped`）与出厂重置（seed/sample）后清空 `insight_reasoning`。
- `.env.example` 补 LLM 变量。

## Capabilities

### Modified Capabilities
- `business-engine`: 刷新语义由推理 Provider 生成后写入缓存；数据变更/重置后缓存失效（避免过期解释被命中）。

## Impact

- 后端：`reasoning/llm.py`、`provider.py`、`cache.py`(无改动或微调)、`models/repository`(失效调用点)、`seed.py`、`routers.py`、`tests/reasoning_check.py`、`.env.example`。
- 无前端改动。
- 验证：reasoning_check（无 key fallback + mock 数值稳定）、run_all 全绿、端点无 key 时返回 fallback 列表。
