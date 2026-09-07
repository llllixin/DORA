## Context

见 proposal.md。清理项来自审查与迭代遗留；目标是等价重构（行为零变化），由门禁证明。

## Goals / Non-Goals

**Goals:** 死代码清除；阈值默认值单一来源；docstring 与现状一致；证据行来自 Repository。

**Non-Goals:** 不改规则语义/计数；不做功能新增；不动归档与文档结构。

## Decisions

- **阈值单源**：`RULE_DEFAULTS` 留在 `engine.py`（含类型化默认值），`seed.py` 遍历它生成 `rule_config` 种子（float 型识别 `isinstance(v, float)` 等）。DB 有值优先逻辑不变（`_rule_map`）。
- **证据 DB 化**：新增 `_evidence_rows_from_repo(kind, repo)` 读 Repository 生成与 `dataset.rows_for_evidence` 等价的原始行（margin/orders/aov/east/high/new_sku/returns/event/cluster）；`engine_evidence` 内部持有默认 Repository 并传入。删除 `engine.py` 对 `dataset.rows_for_evidence` 的调用。
- **docstring**：改描述"Repository（默认 PostgreSQL）+ 规则配置化"。
- 前端删除 `isApiLive/liveSet`（`detectApi`/`syncRemoteData` 保留，后者内部不再写这些标记）。

## Risks / Trade-offs

- 证据 DB 化最易出回归 → 以 `engine_check`（含 c3 kind 断言）+ 冒烟 evidence 各 id 行数/内容等价验证兜底。
- 阈值单源后 seed 计数不变（仍 6 条 rule_config）；仅生成逻辑收敛。
