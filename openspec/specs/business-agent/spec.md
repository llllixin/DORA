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

### Requirement: 问答流支持「后果」意图

系统 SHALL 在 `POST /api/dora/chat` 的意图识别中支持 `consequence` 意图（用户询问「后果/影响/不处理会怎样/风险」类问题），并在 `answer` 文本中产出**带固定前缀**的 `严重等级：` 与 `可能后果：` 段落；两段文本 SHALL 只由该洞察的引擎字段（`severity`/`consequence`/`desc`/`semantics`）组装，数字 SHALL 继续满足既有数字锁。未命中 `consequence` 关键词的问题，意图分类 SHALL 保持既有行为（`why`/`evidence`/`opportunity`/`delegate`/`handle`/`what`）不变。

#### Scenario: 问到后果时返回等级段与后果段
- **WHEN** 提交问题「这条洞察不处理会怎样？」并带对应 `insight_id`
- **THEN** `answer` 文本含 `严重等级：` 与 `可能后果：` 两段，其内容分别与该洞察的 `severity`、`consequence` 字段一致

#### Scenario: 段落前缀稳定可归位
- **WHEN** 前端按前缀把 `answer` 文本拆行归位（`严重等级：` / `可能后果：`）
- **THEN** 两段均可被逐个识别，且不与 `下一步建议：` / `可参考历史先例：` / `主要影响因素：` 段落内容重复

#### Scenario: 既有意图不受影响
- **WHEN** 提交「为什么利润率会失速？」或「证据是什么？」
- **THEN** `intent` 仍分别为 `why` / `evidence`，`answer` 文本结构与本需求引入前保持一致

#### Scenario: 数字锁继续成立
- **WHEN** 检查 `consequence` 意图下 `answer` 文本中出现的数字
- **THEN** 这些数字均出现在该洞察的引擎 payload（`metric`/`delta`/`confidence`/`desc`/`semantics`/`severity`/`consequence`）中
