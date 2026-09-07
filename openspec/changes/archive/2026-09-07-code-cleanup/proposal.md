## Why

C1/C2 全流程审查与 C3/C4 迭代暴露出几笔代码债：`doraApi.isApiLive/liveSet` 死代码、引擎阈值双源（`engine.RULE_DEFAULTS` 与 `seed.rule_items` 各自维护）、`engine.py` docstring 已过期（仍称"内存数据、待接 DB"）、证据行仍取 `dataset.py` 常量而非 DB。本 change 清理后置项，纯工程/重构，不改对外行为（`skip_specs: true`）。

## What Changes

- 前端：删除 `doraApi.ts` 中未使用的 `isApiLive/liveSet`。
- 后端：
  - 阈值单一来源：`seed.rule_items()` 由 `engine.RULE_DEFAULTS` 派生（引擎仍是唯一默认源，DB 值可覆盖）。
  - `engine.py` 顶部 docstring 更新为"Repository 数据源 + 规则配置化"现状。
  - 证据行 DB 化：`engine_evidence()` 不再调用 `dataset.rows_for_evidence()`，改为从 Repository 生成（与种子数据等价，行为不变）。
- `dataset.py` 保留为"种子源"，仅供 seed/数据定义使用。

## Capabilities

<!-- 无（纯重构/工程清理，skip_specs: true） -->

## Impact

- 后端：`app/engine/engine.py`、`app/engine/dataset.py`（仅消费侧收敛）、`app/seed.py`。
- 前端：`frontend/src/services/doraApi.ts`。
- 验证门禁：`tests/run_all`、前端 build、证据端点冒烟必须与改动前一致（回归等价）。
