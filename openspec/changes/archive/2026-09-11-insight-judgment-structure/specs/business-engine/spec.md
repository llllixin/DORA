## ADDED Requirements

### Requirement: 洞察严重等级由数据结构化计算

系统 SHALL 为每条洞察下发 `severity` 字段，等级 SHALL 由数据计算而非模板文案决定：`severity.level` ∈ {`high`, `medium`, `low`}，`severity.score` 为 0–100 的整数，`severity.rule` SHALL 以可读文案说明本次判级口径，`severity.drivers` SHALL 列出参与判级的因子（每项含 `name` 与 `value`，至少一项），`severity.basis` SHALL 固定为 `engine`。判级 SHALL 至少考虑：偏离目标/基线的幅度、连续天数、距阈值距离、影响面（既有快照口径内）。`INSIGHT_TEMPLATES` 的 `tag` 文案 SHALL NOT 参与判级。同一份数据下重复计算的 `severity` SHALL 完全一致。

#### Scenario: 每条洞察都带可解释的等级
- **WHEN** 调用 `GET /api/insights`
- **THEN** 返回的每条洞察均含 `severity`，且 `level` ∈ {high,medium,low}、`score` ∈ [0,100]、`rule` 非空、`drivers` 至少一项、`basis` = `engine`

#### Scenario: 未达阈值的观察项等级不高于已升级问题
- **WHEN** 在同一份数据下比较观察态洞察（`c1`，尚未跌破升级阈值）与问题洞察（`e2`，已跌破升级阈值）
- **THEN** `c1.severity.level` 不高于 `e2.severity.level`，且 `c1.severity.score` 不大于 `e2.severity.score`

#### Scenario: 等级随驱动数据变化
- **WHEN** 驱动信号的数据发生变化（如连续低于目标的天数增加、或距阈值距离缩小）后重新调用 `GET /api/insights/{id}`
- **THEN** 该洞察的 `severity`（`level` 或 `score` 或 `drivers`）随之变化，`tag` 文案保持不变

#### Scenario: 判级数字可回溯且确定
- **WHEN** 检查 `severity.drivers[*].value` 中的数字，并对同一数据源连续计算两次
- **THEN** 这些数字均可在该洞察的引擎 payload（`metric`/`delta`/`desc`/`semantics`/`trigger`）或其快照派生值中找到对应，且两次 `severity` 完全相同

### Requirement: 洞察可能后果由引擎确定性外推

系统 SHALL 为每条洞察下发 `consequence` 字段：`summary`（一句后果判断）、`horizon`（外推观察窗口，如 `3 天`）、`condition`（外推成立条件，如 `若趋势延续`）、`impacts`（受影响项列表，每项含 `name` 与 `value`，至少一项）、`basis`（固定 `engine`）。外推 SHALL 仅使用该洞察同一次计算所用的快照与信号（偏离幅度、连续天数、距阈值距离、影响面等），SHALL NOT 引入快照之外的数字或 LLM 生成的数值。当缺少可用于外推的趋势/阈值字段时，系统 SHALL 输出不含数字的定性后果，而不是臆造数值。同一份数据下重复计算的 `consequence` SHALL 完全一致。

#### Scenario: 每条洞察都带后果与前提
- **WHEN** 调用 `GET /api/insights`
- **THEN** 每条洞察含 `consequence`，其中 `summary`、`horizon`、`condition` 非空，`impacts` 至少一项，`basis` = `engine`

#### Scenario: 后果数字可回溯到快照
- **WHEN** 检查 `consequence.summary` 与 `consequence.impacts[*].value` 中出现的数字
- **THEN** 这些数字均可在该洞察的引擎 payload（`metric`/`delta`/`desc`/`semantics`/`severity`）或其快照派生值中找到对应

#### Scenario: 证据不足时不臆造数值
- **WHEN** 某洞察缺少可用于外推的趋势/阈值字段
- **THEN** 其 `consequence.summary` 为定性表述，且 `impacts[*].value` 不含快照之外的新数字

#### Scenario: 外推确定性
- **WHEN** 同一数据源连续两次调用引擎
- **THEN** 两次返回的每条洞察 `consequence` 完全相同
