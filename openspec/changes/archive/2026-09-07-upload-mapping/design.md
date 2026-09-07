## Context

见 proposal.md。C3 已提供规范直传（datasets 端点）与解析层。本 change 复用 `ingest.py` 的 raw 解析，增加"预览 + 映射校验 + 入库"两段端点与前端紧凑映射步骤。

## Goals / Non-Goals

**Goals:** 预览列结构；按映射把任意列布局转为 series 项并以与 C3 相同的语义落库。

**Non-Goals:** 自动推断列含义；多 sheet；维度参考数据字典；C4 之外的范围。

## Decisions

- **复用 C3 raw 解析**：`ingest` 增加公开函数把"扩展名检查 + csv/xlsx 解析"抽成 `read_rows()`（不做值校验）；`preview` 直接返回 raw 表头与样例。
- **映射最小字段集**：`metric_key`（白名单单选）+ `label_column` + `value_column` + 可选 `dimension_column`/`unit`。保持 JSON mapping 简单可读（前端/API 双用）。
- **校验复用**：映射后构造 items 时复用现有规则（key 白名单、value float、label 非空、range 检查），错误统一 `IngestValidationError` → 400。
- **入库复用**：`replace_series` + `upsert_data_update`，与规范直传完全同语义。
- 前端在**在线分支**先 `previewDataset` 再渲染紧凑映射表单；mock/离线仍走原演示流程，避免大改组件结构。

## Risks / Trade-offs

- 映射字段集合只覆盖"单值列"场景；组合口径（如两列相减）不支持 → 明确非目标，后续扩展。
- 预览会解析整个文件以取表头（xlsx read_only 流式，成本可控）。
- 映射表单会增大 DataSourcePicker 状态面 → 控制为一次性 `mapping` 状态，不引入路由。
