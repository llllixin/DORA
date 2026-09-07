## Purpose

提供经营数据文件的入库接口：接受 CSV/XLSX 的"引擎输入规范格式"，完成解析校验、事务性写入 PostgreSQL Repository 并登记数据更新事件，使引擎数据源可被外部文件驱动更新。

## ADDED Requirements

### Requirement: 上传规范格式数据集
系统 SHALL 接受 `POST /api/datasets`（multipart 文件），支持 `.csv`（标准库解析）与 `.xlsx`（openpyxl 解析）；内容为引擎输入规范格式（表头含 `metric_key,label,dimension,value,unit`），维度支持 demo 全指标 key（margin/returns/orders/revenue/aov/east_orders/new_sku/high_value/supplier_price）。

#### Scenario: 合法文件入库并登记更新事件
- **WHEN** 上传一个通过校验的规范 CSV/XLSX
- **THEN** 返回 `{ok, name, rows, affectedMetrics, updated}`，对应指标系列被替换，且 `data_update_log` 新增一条事件

#### Scenario: 非法文件返回 400
- **WHEN** 上传内容缺列、数值非法或指标 key 不支持
- **THEN** 返回 `400` 且响应含可读错误详情，数据库不变更

#### Scenario: 数据库离线时上传返回 503
- **WHEN** 数据库不可用而调用上传接口
- **THEN** 返回 `503`（不回退 Mock、不写半截数据）

### Requirement: 载入内置样例与数据源摘要
系统 SHALL 提供 `POST /api/datasets/sample`（服务端幂等种子，返回各表行数）与 `GET /api/datasets/current`（最近更新时间/新增行/受影响指标/各表行数）。

#### Scenario: 服务端载入样例
- **WHEN** 调用 `POST /api/datasets/sample`
- **THEN** 返回各表行数且重复调用不翻倍（幂等）

#### Scenario: 查看当前数据源
- **WHEN** 调用 `GET /api/datasets/current`
- **THEN** 返回最近一次更新元数据与 Repository 各表行数
