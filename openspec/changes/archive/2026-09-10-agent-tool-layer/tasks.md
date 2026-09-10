## 1. 工具层 · query_metric

- [x] 1.1 `Repository.list_metric_series(metric_key, dimension=None, limit=200)`：按 metric_key（可选 dimension）读 `metric_series` 序列行，升序返回 → 验证：`GET /api/tools/query_metric?metric_key=margin` 返回 `count>0` 且行含 `label/value/unit`（agent_check [1] ✅）
- [x] 1.2 `GET /api/tools/query_metric`（只读、未知指标空数组不 404）→ 验证：`metric_key=not_exist` 返回 `{count:0, rows:[]}`（HTTP 200）（agent_check [1] ✅）

## 2. RAG 检索 · knowledge/search

- [x] 2.1 `Repository.search_knowledge(query, types, top_k)`：词法打分排序（确定性）→ 验证：造一条 knowledge 行后查询命中，`score>0`；无关词返回空（agent_check [2] ✅）
- [x] 2.2 `POST /api/knowledge/search`：返回 `hits[]`（含 `entry_type/source_id/code/title/score`）+ `references[]`；空命中 `empty=true` → 验证：命中时 `references[0].source_id` 可回溯到该行；无关词 `empty=true`（agent_check [2] ✅）

## 3. Agent 运行记录 · agent_run

- [x] 3.1 `models.AgentRun` + `create_agent_run / append_agent_run_event / get_agent_run / list_agent_runs / delete_all_agent_runs` → 验证：create→get 字段一致；append 后 events 长度 +1（agent_check [3] ✅）
- [x] 3.2 `POST /api/agent/runs`、`GET /api/agent/runs/{id}`、`POST /api/agent/runs/{id}/events`（不存在 404）→ 验证：HTTP 往返；`id` 形如 `r-<hex12>`（agent_check [3] ✅）

## 4. Dora Chat · SSE

- [x] 4.1 `POST /api/dora/chat`：SSE 输出 `thought_step / tool_call / evidence / answer / done`，并落一条 `agent_run(trigger=chat)` → 验证：响应含 5 类事件、`done.run_id` 可 `GET /api/agent/runs/{id}` 查到（agent_check [4] ✅）
- [x] 4.2 数字锁：答案文本中的数字必须来自引擎/证据字段 → 验证：`agent_check` 断言答案数字集合 ⊆ 引擎 payload 数字集合（首版曾因模板「连续 3 天」与「1)2)3)」编号越界被断言拦下并已改为中文数字/无编号）
- [x] 4.3 意图分类规则（why/evidence/opportunity/delegate/handle/what）→ 验证：`thought_step.intent` 正确（why 命中「为什么」；agent_check [4] ✅）

## 5. 门禁与回归

- [x] 5.1 `tests/agent_check.py` 覆盖 1–4（含自清）→ 验证：`python3 -m tests.agent_check` → `agent_check OK（工具层 / 知识检索 / 运行记录 / 问答流 4 节）`
- [x] 5.2 `tests/run_all.py` 增加 `agent_check`（7 段 → 8 段）→ 验证：重启后端后 `python3 -m tests.run_all` → **ALL GREEN**
- [x] 5.3 文档同步：workflow.md §6.2 标记已建 + §11 补新端点；dev-log 迭代 42；持续优化；AGENT/hub/README（能力 7 个、端点 37、8 段）

