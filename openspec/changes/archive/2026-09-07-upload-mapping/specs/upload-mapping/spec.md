## Purpose

为任意列布局的经营数据文件提供"列→引擎口径"的映射上传能力：先预览文件列结构，再以映射声明（数值列/标签列/维度列/指标 key）完成校验与入库，作为 C3 规范直传的补充路径。

## ADDED Requirements

### Requirement: 文件列结构预览
系统 SHALL 通过 `POST /api/datasets/preview` 上传文件（csv/xlsx，不落库）并返回表头列清单与前若干行样例；错误语义与上传一致（400/413/503）。

#### Scenario: 预览返回列与样例
- **WHEN** 上传任意含表头的 csv/xlsx
- **THEN** 返回 `columns`（按出现顺序去重）与 `sampleRows`（前 ≤10 行）
#### Scenario: 预览非法文件返回 400
- **WHEN** 上传空/无表头/超限文件
- **THEN** 返回 400/413 可读错误

### Requirement: 映射上传并入库
系统 SHALL 接受 `POST /api/datasets/mapped`：`mapping` 含 `metric_key`（白名单）、`label_column`、`value_column`、可选 `dimension_column`/`unit`；对每行执行校验（label 非空、value 数值、key 白名单），通过后事务替换对应 key 的系列并登记数据更新事件。

#### Scenario: 映射文件成功入库
- **WHEN** 上传列布局文件并提交合法映射（如 metric_key=margin、label_column=date、value_column=margin_value）
- **THEN** 返回 `{ok,name,rows,affectedMetrics,updated}`，`/api/insights?type=problem` 等按新数据变化
#### Scenario: 映射非法（缺列/数值错/key 不支持）返回 400
- **WHEN** 映射引用了不存在列、value 列含非数值、或 key 不在白名单
- **THEN** 返回 400 可读错误且数据库不变更
