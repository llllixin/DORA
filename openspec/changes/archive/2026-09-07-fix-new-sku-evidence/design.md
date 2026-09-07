## Context

见 proposal.md - Why。证据行由 `dataset.rows_for_evidence(kind)` 生成（D016 边界：仍以种子源辅助生成，与 DB 内容镜像）；c3 信号目前 `evidence_kind='margin'` 属遗留占位。

## Goals / Non-Goals

**Goals:** 让 c3 证据链展示新品销量数据；加自检断言防回归。

**Non-Goals:** 不改 c2/o2/其它证据；不动规则与 semantics；不做本轮审计其余清理（死代码/阈值双源/过期 docstring——记入路线图后置）。

## Decisions

- **在 `rows_for_evidence()` 增加 `new_sku` kind**，用现有 `NEW_SKU_WEEKS/NEW_SKU_VALUES` 生成「周标签/新品销量/件」行——与证据生成器既有模式一致（备选：新建独立模块，过重，否决）。
- **把 `sig-new-sku.evidence_kind` 从 `margin` 改为 `new_sku`**，`EVIDENCE_META` 增加对应 sheet/path 描述。
- engine_check 增加最小防回归断言（kind ≠ margin 且首行含「新品销量」），对齐 spec 场景。

## Risks / Trade-offs

- 证据仍来自种子常量而非 DB 行（既有 D016 边界）；本修复保证"内容与主题一致"，彻底 DB 化并入 C3。
- 无其它风险：字段形状不变、前端零改动。
