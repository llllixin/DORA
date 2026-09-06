## Why

V2 引擎（迭代 6–8）目前只覆盖 7 条洞察：c2（数据更新事件）与 o2（华东高客单门店集群机会）仍走旧静态数据兜底，导致"页面看到的两类洞察不是引擎算出来的"。数据更新是 Dora"主动循环"的燃料事件、门店集群是机会语义的关键场景，不补齐会让 V2 引擎覆盖留洞、前后端数值出现"引擎 + 快照"混用。

## What Changes

- 引擎数据集新增两类源数据：数据更新事件（更新时间/新增行/被影响指标）与华东高客单门店集群（Top 门店分布、区域占比、商品共性）。
- 引擎新增两条规则信号并生成对应洞察：
  - `c2`（change · 数据更新事件）：数据就绪后形成可追溯的"更新事件"洞察。
  - `o2`（opportunity · 高客单门店集群）：Top 高客单门店区域性聚集且存在商品/动作共性 → 机会候选。
- 引擎为 c2/o2 补齐 semantics（原因链 + 下一步）与 evidence（非占位原始行）。
- 前端/API 契约**不变**：字段仍与现有 Insight 相同；`/api/insights?type=change|opportunity` 列表、`/api/evidence/c2|o2` 由引擎直接产出，命中时不再走静态兜底。
- 观测数字变化：changes 计数由 3 → 4，opportunities 由 1 → 2，watch 随 changes 同步。

## Capabilities

### New Capabilities
- `business-engine`: Dora 确定性业务引擎对外行为——输入原始经营数据，输出 Pulse 摘要与三类洞察（problem/opportunity/change）及对应证据/语义；本变更建立该能力的第一版正式 spec，覆盖"哪些经营情形会生成哪类洞察"的行为规则。

### Modified Capabilities
<!-- 首次建立 capability，暂无既有 spec 需修改 -->

## Impact

- 后端：`backend/app/engine/dataset.py`、`backend/app/engine/engine.py`（规则/模板/semantics/evidence）、`backend/tests/engine_check.py`（断言 c2/o2 出现、计数变化）。
- 前端：**无代码改动**；Pulse 摘要/洞察 Tab 计数已数据驱动，会自动跟随（changes 4、opportunities 2）；Watch 页 c2/o2 行从"历史 id 兜底"转为真实引擎项。
- API：无破坏性变更；`GET /api/insights?type=…`、`GET /api/evidence/{id}` 行为不变、来源变为引擎。
- 非目标（明确不做）：Watch 升级调度/阈值自动升级执行（属 V4）；PostgreSQL 落库（属 C2）。
