## ADDED Requirements

### Requirement: 无指标数据时不产洞察
当 Repository 中不存在任何 `metric_series` 数据时，引擎 SHALL 返回空 Pulse（各计数 0、`last_updated='--'`）且不产出任何洞察——即使更新事件或门店集群表仍残留数据。

#### Scenario: 指标序列清空后引擎静默
- **WHEN** `metric_series` 为空而 `data_update_log`/`store_cluster_store` 仍有数据
- **THEN** `/api/insights` 为空、`/api/pulse` 计数为 0 且 `last_updated='--'`

### Requirement: 阈值比较语义显式化
引擎 SHALL 以规则函数表达阈值比较：目标线"低于"用严格小于（值==目标不触发）；升级阈值"跌破"默认含等于（值==阈值即升级）。语义须有单元断言固定。

#### Scenario: 等于目标不触发、等于升级阈值触发
- **WHEN** margin 恰好等于目标 18.5 → 不产 p1；华东跌幅恰好等于 -3.0 → 产 e2

### Requirement: 时间戳取自更新事件
洞察证据的 `updated` 与 Pulse 的 `last_updated` SHALL 来自最新 `data_update`；无更新事件时显示 `--`。

#### Scenario: 证据与脉搏时间跟随更新事件
- **WHEN** 最新更新事件时间变化（如 23:59）或事件被清空
- **THEN** `/api/evidence/*.updated` 与 `/api/pulse.last_updated` 反映最新事件时间或 `--`
