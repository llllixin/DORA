## Why

审查 C1 时发现：change 洞察 `c3`（新品销量 ↑35.2%）的证据链仍指向 `margin` 占位数据——用户打开 `/api/evidence/c3` 看到的是「利润率 18.4%」等无关行，属于会误导的高价值缺陷。

## What Changes

- `dataset.rows_for_evidence()` 新增 `new_sku` kind：用新品周销量源数据生成原始行。
- 引擎 `sig-new-sku` 的 `evidence_kind` 从 `margin` 改为 `new_sku`；`EVIDENCE_META` 增加 `new_sku` 描述。
- `engine_check` 增加断言：c3 的 evidence 不再为 margin 且首行为新品销量数据。
- 端点 `/api/evidence/c3` 输出随之变为新品数据。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `business-engine`: 洞察证据语义修正——「新品销量快速增长」洞察（c3）的证据链须展示新品销量原始行，而非其它指标占位数据。

## Impact

- 后端：`backend/app/engine/dataset.py`、`backend/app/engine/engine.py`、`backend/tests/engine_check.py`。
- 前端：无改动（证据抽屉按 id 消费，字段形状不变）。
- 非目标：不动 o2/c2 证据、不动规则/语义；其余审查项（死代码、阈值双源等）记入路线图后置。
