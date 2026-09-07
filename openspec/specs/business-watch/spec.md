# business-watch Specification

## Purpose
Dora"持续关注（Watch）"能力的行为契约：用户以一句话把业务目标委托给 Dora（WatchTarget：指标/范围/条件/频率），系统按频率或数据更新评估并持久化命中事件（WatchEvent），把变化送回业务脉搏并按条件升级——本能力保证委托与命中记录可持久化存取、可追溯，为"委托→评估→事件→回脉搏"闭环提供数据层契约（判定仍由确定性引擎负责，Watch 不伪造 problem/opportunity 身份）。

## 需求来源表（Traceability）

| 需求 | 由谁新增 | 归档 change | 迭代 |
|---|---|---|---|
| 委托与命中事件可持久化存取 | V4-T1 Watch 领域 | `changes/archive/2026-09-07-v4-watch-domain` | 22 |
| 委托语句可解析为结构化委托（显式确认） | V4-T2 委托解析 | `changes/archive/2026-09-07-v4-watch-parser` | 23 |

## Requirements

### Requirement: 委托与命中事件可持久化存取
系统 SHALL 提供 `watch_target` 与 `watch_event` 的持久化：一个 watch target 记录"原始委托语句 + 解析结果（metric_key/dimension/condition/frequency）"与当前状态（watching|paused）；一个 watch event 记录某次命中（时刻/kind=change|escalate/文案/前后值），并归属且仅归属一个 target。Repository SHALL 支持创建、列表、单查、改状态、删除（删除级联清理其全部事件）与整体清空原语，数据库不可用时与现有读接口一致抛"数据源不可用"。

#### Scenario: CRUD 往返保留委托与状态
- **WHEN** 创建一条 watch target（含解析结果 JSON、status=watching、frequency=on_update），随后列表、按 id 单查、暂停（paused）后再单查
- **THEN** 各次读回的结构化字段与写入一致，暂停后 status=paused；不存在的 id 单查返回空（不抛错）

#### Scenario: 命中事件级联与删除
- **WHEN** 对同一 target 追加 change 与 escalate 两类事件后删除该 target
- **THEN** 事件列表按序返回该 target 的两条事件；删除后 target 与其全部事件均不可再查（幂等，重复删除不抛错）

### Requirement: 委托语句可解析为结构化委托（显式确认）
系统 SHALL 提供解析入口：把中文委托语句（"关注什么指标/范围，什么条件下提醒"）解析为结构化 intent（`metric_key`、`dimension`、`condition{type,days?,ref?,ref_is_pct?}`、`frequency?`、显示 `label`）；仅当指标命中引擎受支持的词典时才返回 `ok=true`，否则 `ok=false` 且返回 `unsupported`（原因：不支持的指标/未识别），绝不静默假设成别的指标。未识别触发条件时 SHALL 返回建议默认"连续 3 天下降"并标记 `condition_defaulted=true`（供确认界面展示，不隐藏）。

#### Scenario: 支持句式解析成功
- **WHEN** 解析 "帮我关注华东销售额，如果连续三天下降就提醒我"
- **THEN** `ok=true`，intent 为 `metric_key=east_orders, dimension=华东, condition={type:streak_below,days:3}, label=华东销售额`

#### Scenario: 值跌破与频率词
- **WHEN** 解析 "关注利润率，跌破 18% 就提醒我，每天 09:00 检查"
- **THEN** `ok=true`，intent `condition={type:below,ref:18.0,ref_is_pct:true}`，`frequency=daily 09:00`，`condition_defaulted=false`

#### Scenario: 不支持的指标显式拒绝
- **WHEN** 解析 "关注库存周转，连续 3 天下跌就提醒我"
- **THEN** `ok=false`，`intent=null`，`unsupported` 含该指标与"暂不支持/可用指标"提示
