## Why

V2 边界审查发现的 5 个修复点：空指标序列下事件/集群类洞察仍误触发；阈值比较语义未显式抽象；证据时间戳硬编码；无数据时 last_updated 给旧值；Pulse 数据源名称硬编码、watching 口径为静态展示。合并为一个 change 便于测试与发布。

## What Changes

- 后端（必做）
  1. **空数据门禁**：Repository 无任何 metric_series 时，引擎不产出洞察（Pulse 全 0、`last_updated='--'`），杜绝"只清系列但 cluster/event 残留"导致 c2/o2 无依据触发。
  2. **阈值比较规则化**：新增规则函数 `_below`（严格 `<`，margin 目标语义）与 `_breach(actual, threshold, inclusive)`（东华升级默认含等 `<=`）；写引擎单元断言固化语义。
  3. **时间戳动态化**：`engine_evidence.updated` 与 pulse `last_updated` 改从最新 `data_update` 取值；无事件显示 `--`。
- 前端（建议做）
  4. Pulse 状态栏数据源名称由后端/`dataSrc` 下发（App 传入 `dataLabel`），不再硬编码。
  5. "持续关注"计数旁加 `?` 悬浮说明"当前为静态展示"（Native tooltip）。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `business-engine`: 引擎空数据行为与阈值语义的边界契约——无指标数据时不得产出洞察；阈值比较的"严格小于/含等于"语义显式化；时间显示取自最新更新事件。

## Impact

- 后端：`app/engine/engine.py`（门禁/规则函数/时间戳）、`backend/tests/engine_check.py`（新增边界断言）。
- 前端：`src/features/pulse/PulsePage.tsx`、`src/App.tsx`（传 dataLabel）、`src/styles.css`（`?` 悬浮）、`src/components/ui/Tag.tsx` 不动。
- 验证：`python3 -m tests.run_all` 全绿 + `npm run build` + 冒烟。
