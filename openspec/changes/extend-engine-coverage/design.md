## Context

现状（见 proposal.md - Why）：引擎已产出 7 条洞察并接入 `/api/pulse|insights|evidence`（迭代 6–8），c2/o2 仍走 `app/data.py` 静态快照兜底。引擎结构为单一流水线 `dataset.py → compute_snapshot() → evaluate_signals() → build_insights()/engine_evidence()`，洞察文案用模板占位（D014），页面语义来自 `semantics` 内联字段（D015）。

## Goals / Non-Goals

**Goals:**
- 以最小侵入扩展同一流水线：数据源 → 快照 → 信号 → 洞察/证据，全部沿用现有函数与字段形态。
- c2/o2 的 metric/delta/semantics/evidence 数值全部来自新增源数据，不使用静态字符串。
- 引擎自检覆盖新场景，路由响应来源切换后无静态兜底命中。

**Non-Goals:**
- 不实现"更新后自动触发重算"或 Watch 升级调度（V4）。
- 不迁移 PostgreSQL（C2）；不做前端代码改动（计数已数据驱动）。

## Decisions

- **c2 建模为"元数据事件信号"，而非伪造一条经营指标序列**。数据更新是事件型变化（rows_added/时间/受影响的指标清单），按 change 语义输出"观察态"洞察。
  - 备选：为 c2 造一组"更新数量时间序列"再走趋势检测 → 语义失真且引入伪数据，否决。
- **o2 建模为"集群检测信号"**：在 `dataset.py` 提供门店集群聚合（Top 高客单门店的区域分布、占比、共性商品占比），快照计算区域占比与代表客单价，规则用"区域占比 ≥ 阈值（如 60%）"触发。
  - 备选：把 o2 退化成静态文案模板 → 违反"引擎覆盖=算出来"的变更目标，否决。
- **证据行走 `rows_for_evidence(kind)` 扩展**：为 c2/o2（以及需要时 c3/returns 细节）增加新 kind 的原始行生成，证据仍与 Insight 解耦、可独立验证。
- **不做契约变更**：复用现有 Insight/Evidence 字段与 semantics 内联形态（D015）；静态 `INSIGHTS/EVIDENCE` 保留给 Watch 等其它域，路由引擎分支命中后自然不再兜底。

## Risks / Trade-offs

- 计数变化（opportunities 1→2、changes 3→4）会改变 Pulse 卡片与 Tab 数字 → 前端已数据驱动，属预期行为；需在引擎自检中断言新计数。
- c2/o2 属于"演示数据推演"场景，若后续接真实数据，其触发条件需由真实口径校准 → 规则阈值在 C2（配置化）中收敛，本变更在设计中注明默认值来源。
- 新增源数据会扩大 `dataset.py`，但保持每类数据自带 rows_for_evidence，避免证据与判定状态散落。

## Migration Plan

- 后端无破坏性变更；`/api/insights|evidence` 响应结构不变。
- 先扩展 dataset/snapshot/规则并跑引擎自检，再（无需前端改动）观察 5173 页面计数跟随。
- 回滚：单次提交粒度，直接 revert 即可恢复静态兜底行为。
