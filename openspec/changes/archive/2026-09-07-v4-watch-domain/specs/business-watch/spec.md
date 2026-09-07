## ADDED Requirements

### Requirement: 委托与命中事件可持久化存取
系统 SHALL 提供 `watch_target` 与 `watch_event` 的持久化：一个 watch target 记录"原始委托语句 + 解析结果（metric_key/dimension/condition/frequency）"与当前状态（watching|paused）；一个 watch event 记录某次命中（时刻/kind=change|escalate/文案/前后值），并归属且仅归属一个 target。Repository SHALL 支持创建、列表、单查、改状态、删除（删除级联清理其全部事件）与整体清空原语，数据库不可用时与现有读接口一致抛"数据源不可用"。

#### Scenario: CRUD 往返保留委托与状态
- **WHEN** 创建一条 watch target（含解析结果 JSON、status=watching、frequency=on_update），随后列表、按 id 单查、暂停（paused）后再单查
- **THEN** 各次读回的结构化字段与写入一致，暂停后 status=paused；不存在的 id 单查返回空（不抛错）

#### Scenario: 命中事件级联与删除
- **WHEN** 对同一 target 追加 change 与 escalate 两类事件后删除该 target
- **THEN** 事件列表按序返回该 target 的两条事件；删除后 target 与其全部事件均不可再查（幂等，重复删除不抛错）
