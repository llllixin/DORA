# business-agent Specification

## Purpose

Dora Agent 层的行为契约：**Agent 只能通过只读工具观察系统、通过可回溯引用使用历史知识、其运行轨迹可持久化回放；问答流不产生新判定与新数字**。为 Dify 工作流（`docs/workflow.md`）提供后端能力面（工具层 / 知识检索 / 运行记录 / 问答流）。

## 需求来源表（Traceability）

| 需求 | 由谁新增 | 归档 change | 迭代 |
|---|---|---|---|
| Agent 工具层可查询指标序列 | agent-tool-layer | `changes/archive/2026-09-10-agent-tool-layer` | 42 |
| 知识检索返回可回溯引用 | agent-tool-layer | `changes/archive/2026-09-10-agent-tool-layer` | 42 |
| Agent 运行可持久化与回放 | agent-tool-layer | `changes/archive/2026-09-10-agent-tool-layer` | 42 |
| 问答流只引用引擎判定与证据（数字锁） | agent-tool-layer | `changes/archive/2026-09-10-agent-tool-layer` | 42 |

## Requirements

### Requirement: Agent 工具层可查询指标序列

系统 SHALL 提供只读工具端点 `GET /api/tools/query_metric`，按 `metric_key`（可选 `dimension`）返回 `metric_series` 的序列行（`label/value/unit/dimension`）；当指标不存在时 SHALL 返回空数组而非错误；工具 SHALL NOT 返回引擎未持久化的臆造数值。

#### Scenario: 命中指标返回序列
- **WHEN** 请求 `GET /api/tools/query_metric?metric_key=margin`
- **THEN** `ok=true`、`count>0`，每行包含 `label/value/unit`

#### Scenario: 未知指标返回空数组
- **WHEN** 请求 `GET /api/tools/query_metric?metric_key=not_exist`
- **THEN** HTTP 200、`count=0`、`rows=[]`（不抛 404、不编造数据）

### Requirement: 知识检索返回可回溯引用

系统 SHALL 提供 `POST /api/knowledge/search`，对知识归档（`knowledge_archive`）做检索并返回 `hits[]` 与 `references[]`；每个 `reference` SHALL 包含 `entry_type/source_id/code/title`，可回溯到具体归档行；命中为空时 SHALL 返回 `empty=true`，SHALL NOT 返回编造的引用。

#### Scenario: 命中并返回引用
- **WHEN** 对一个存在知识条目的关键词发起检索
- **THEN** `hits` 非空、`references` 与 `hits` 对应且 `source_id` 指向真实归档行

#### Scenario: 无命中显式为空
- **WHEN** 检索词与语料无关（或语料为空）
- **THEN** `empty=true`、`hits=[]`、`references=[]`

### Requirement: Agent 运行可持久化与回放

系统 SHALL 持久化 Agent 运行记录（`agent_run`：trigger/status/input/events/output），并暴露 `POST /api/agent/runs`、`GET /api/agent/runs/{id}`、`POST /api/agent/runs/{id}/events`；运行 id SHALL 形如 `r-<hex12>`；对不存在 id 的读写 SHALL 返回 404。

#### Scenario: 创建-读取-追加一致
- **WHEN** 创建一条运行记录后读取，再追加一个事件后再次读取
- **THEN** 首读字段与创建一致；追加后 `events` 增一且顺序保持

### Requirement: 问答流只引用引擎判定与证据（数字锁）

系统 SHALL 提供 `POST /api/dora/chat`，以 SSE 输出 `thought_step/tool_call/evidence/answer/done` 事件，并落一条 `agent_run`；答案文本 SHALL 仅由引擎字段（洞察 `title/desc/metric/delta/source/semantics`）与证据、检索引用组装，SHALL NOT 引入引擎外的新数字或新判定；无可引用历史时 SHALL 显式说明"暂无先例"。

#### Scenario: 事件序列完整且可回放
- **WHEN** 提交一个针对引擎判定的问题
- **THEN** 流中出现 5 类事件，`done.run_id` 可在 `GET /api/agent/runs/{id}` 查到

#### Scenario: 数字锁
- **WHEN** 检查 `answer` 文本中出现的数字
- **THEN** 这些数字均出现在该洞察的引擎 payload（metric/delta/confidence/desc/semantics 等）中
