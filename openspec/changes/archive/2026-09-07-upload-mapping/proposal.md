## Why

C3 只接受"引擎输入规范格式"文件，任意业务文件必须先手工转格式，冷启动体验断裂。C4 补上"口径确认/字段映射"：上传后让用户（或下游系统）声明"哪列是数值、哪列做标签/维度、归属哪个指标口径"，后端完成映射入库——承接 Metric Definition 语义。

## What Changes

- 后端新增：
  - `POST /api/datasets/preview`：上传文件仅解析（不落库），返回表头列清单与前若干行样例，供前端做映射选择。
  - `POST /api/datasets/mapped`：multipart 文件 + JSON `mapping`（`metric_key`、`label_column`、`value_column`、可选 `dimension_column`/`unit`）；后端按映射把每行转成 series 项并**走与 C3 相同的校验**（key 白名单、数值、label 非空）后事务替换落库 + 登记更新事件。
- 复用 C3 解析层（csv 标准库 / xlsx openpyxl）与校验错误语义（400/413/503）。
- 前端：文件选择后（后端在线时）先预览列，再显示**紧凑映射表单**（选 metric_key、value/label/dimension 列），确认后入库并回写数据源；离线回退原有行为。
- `metric_key` 候选仍为白名单（margin/returns/orders/revenue/aov/east_orders/new_sku/high_value/supplier_price）。

## Capabilities

### New Capabilities
- `upload-mapping`: 任意列布局文件的"列→口径"映射接口——预览列结构、提交映射并入库的对外行为。

### Modified Capabilities
- `data-ingest`: 在"规范格式直传"之外新增"映射上传"路径；校验语义与更新事件保持与 C3 一致。

## Impact

- 后端：`app/ingest.py`（导出 raw 解析/预览/映射校验）、`app/routers.py`（两个端点）、`backend/tests/ingest_check.py` 增映射用例。
- 前端：`doraApi` 增 `previewDataset/mappedDataset`；`DataSourcePicker` 增加映射步骤（在线分支）。
- 非目标：自动智能推断列含义（ML/启发式，后续再说）；多 sheet 选择；维度校验字典。
