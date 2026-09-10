## Why

`docs/workflow.md` §6.2 列出「多 Agent / RAG / 工作流」落地所需的后端能力，而当前只有判定/证据/委托/行动/知识 REST，缺四块：① 显式**指标查询工具**（Agent 可直接调用，而不是从证据里猜）；② **知识检索端点**（RAG 的 references 面）；③ **Agent 运行记录**（轨迹可回放/审计）；④ **Dora Chat SSE**（thought_step/tool_call/evidence/answer 流，供 AskBar/FollowupCard 逐块渲染）。本 change 以最小闭环补齐这四项，让 Dify 工作流可以直接调用（对应 workflow.md §11 配置手册）。

## What Changes

- **工具层**：`GET /api/tools/query_metric?metric_key=&dimension=&limit=` —— 按口径读 `metric_series` 序列行；未知指标返回空数组（不 404），只读、确定性。
- **RAG 检索**：`POST /api/knowledge/search {query, types?, top_k?}` —— 对 `knowledge_archive` 做**词法打分** top-k，返回 `hits[]` 与可回溯 `references[]`；命中为空时 `empty=true`（诚实，不编造）。向量化（embedding/pgvector）留后续 change。
- **Agent 运行记录**：新表 `agent_run`（events 用 JSON 列，回放友好）+ `POST /api/agent/runs`、`GET /api/agent/runs/{id}`、`POST /api/agent/runs/{id}/events`。
- **Dora Chat**：`POST /api/dora/chat` —— SSE 输出 `thought_step / tool_call / evidence / answer / done`；答案由**引擎字段 + 模板语义**组装（不引 LLM 依赖、不产生数字），并落一条 `agent_run`（`trigger=chat`）。
- **门禁**：新增 `tests/agent_check.py` 并纳入 `run_all`（7 段 → **8 段**）。
- **新建能力 spec** `business-agent`（只读工具 / 检索引用 / 运行轨迹 / 流式问答 + 数字锁）。

## Capabilities

### New Capabilities
- `business-agent`: Agent 工具层、知识检索、运行记录与问答流的行为契约（工具只读且确定性、检索必须回填可回溯引用、运行事件可持久化回放、问答流四类事件且数字只来自引擎/证据）。

### Modified Capabilities
（无。判定语义、委托、行动、知识入库均不变。）

## Impact

- 后端：`app/models.py`（`agent_run`）、`app/repository.py`（工具/检索/运行记录方法）、`app/routers.py`（4 个端点 + SSE）、`app/schemas.py`（3 个请求模型）、`tests/agent_check.py`、`tests/run_all.py`。
- 前端：无改动（消费方是 Dify）。
- DB：新增一张表（`create_all` 自动建；无破坏性迁移）。
- 文档：`docs/workflow.md` §6.2 标记已建 + §11 配置手册补新端点；dev-log/持续优化/AGENT/README 索引同步。
