## Context

- 现状：31 个 REST 端点覆盖 判定/证据/委托/行动/知识/上传/解释；LLM 只用于解释文案；`knowledge_archive`/`case_lesson` 是纯文本表；无向量库、无任务队列（D009 推迟）、无 Agent 运行记录。
- `run_all` 目前 7 段（engine/ingest/reasoning/golden/e2e/watch/action）；本 change 加 `agent_check` → 8 段。
- Dify 工作流（`docs/workflow.md`）需要：query_* 工具、knowledge/search、agent/runs、/dora/chat。

## Goals / Non-Goals

**Goals:**
- 四项能力最小闭环，全部 **确定性**（无 LLM 也可跑、可断言），Dify 可直接调用。
- 检索必须回填 `references`（可回溯到 `entry_type/source_id/code`）；无可引用时显式 `empty=true`。
- 问答流事件与 workflow.md §10.1 对齐；答案数字只来自引擎/证据字段。
- 运行记录可 `create/get/append`，可回放。

**Non-Goals:**
- 向量检索 / embedding / pgvector（另立 change）。
- 多 Agent 会商编排（Dify 侧负责）、真实外部工具执行、job/SSE 任务队列、Confidence Aggregator。
- 不改判定/证据/委托/行动/知识的既有语义与端点。

## Decisions

### D1 检索先做词法打分（确定性、零依赖）
`search_knowledge`：对 `title+content+note+code` 做 token 命中打分（ASCII 词 + ≥2 字中文片段；整串命中 +3），按 `(score, created_at)` 倒序取 top-k。
- 为什么：可断言、无外部服务、不改部署；Dify 侧也可先用自身知识库，后端检索作为"自带 RAG"。
- 备选：直接上 pgvector → 引入扩展与 embedding 服务，超出本 change（另立）。

### D2 Chat 用「引擎字段 + 模板语义」组装，不引 LLM 依赖
`/api/dora/chat` 只读引擎快照 + 证据 + 检索引用，按意图（why/evidence/opportunity/delegate/handle/what，规则分类）拼答案；`number_source="engine"`。
- 为什么：与既有"LLM 只改文案、不改判定/数字"红线一致；无 key 环境也能确定性测试（run_all 钉死 template）。
- 备选：直接调 LLM 生成 → 不可断言、$ 成本与延迟不可控；留作后续（复用 reasoning provider 即可）。

### D3 `agent_run` 用 JSON 列存 events（单表）
表：`id(r-<hex12>)/trigger/status/input(JSON)/events(JSON)/output(JSON)/created_at/updated_at`。
- 为什么：轨迹是"事件数组"，单表 + JSON 足够回放；避免 run/event 双表 join 与迁移成本。

### D4 SSE 先落库再流式（同源可回放）
先生成确定性的 events 列表并 `create_agent_run`，随后按 `event:` 分帧推送（含 `done{run_id}`）；`text/event-stream`。
- 为什么：事件与落库天然一致（不会出现"流了但没记录"）；真实流式 LLM 属后续。

## Risks / Trade-offs

- [词法检索召回有限] → 明确 Non-Goal；`empty=true` 时问答话术显式"暂无先例"，不假装召回。
- [SSE 测试依赖后端进程] → `agent_check` 与 `e2e_api_check` 同模式（HTTP 到 :8000），归档 gate 已要求后端在线。
- [新增表在旧库] → `create_all` 自动建表；不新增列类型变更，无 ALTER 需求。
- [Dify 侧重复实现检索] → 允许：Dify 知识库与后端检索二选一或互补，契约一致（都回填 references）。

## Migration Plan

1. 代码：models(agent_run) → repository 方法 → routers/schemas → tests/agent_check + run_all。
2. 建表：重启后端（`create_all`）或 `python -m app.db`(init)。
3. 回滚：`git revert`；表可保留（无外键依赖，不影响既有功能）。
