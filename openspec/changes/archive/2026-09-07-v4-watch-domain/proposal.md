# v4-watch-domain

## Why

V4（Watch 真实委托，路线图 §3B）把"持续关注"从前端静态列表升级为后端真实委托。V4-T1 是整个 V4 的**地基**：`watch_target`（一句话委托 + 解析结果）与 `watch_event`（命中历史）必须先能持久化、可 CRUD、可清空，后续 T2 解析、T3 评估、T4 前端、T5 E2E 才有稳定的数据层契约。当前 `insight_reasoning` 之后新增表全部走 SQLAlchemy + Repository 会话模式，本 change 延续该模式，不引任何新依赖、不动引擎行为。

## What Changes

- 新增 SQLAlchemy 模型：`WatchTarget`（原文 text、解析结果 intent JSON、状态 status、频率 frequency、last_checked_at/last_event_at/created_at）与 `WatchEvent`（target 外键、触发时刻、kind=change|escalate、事件文案 summary、前后值 values JSON）。
- Repository 增补 CRUD 原语（与现有风格一致：短会话 + `DataSourceUnavailableError` 包装）：
  - `create_watch_target(text, intent, status, frequency)` → 带 `id`（`w-` + 随机短 id）
  - `list_watch_targets()` / `get_watch_target(id)`（含最近命中事件概要）
  - `set_watch_status(id, status)`（watching|paused）
  - `delete_watch_target(id)`（**级联清其事件**，幂等：不存在不抛错）
  - `add_watch_event(target_id, kind, summary, values)` / `list_watch_events(target_id)`
  - `delete_all_watch_targets()`（后续出厂重置/T3 接线用）
  - `count_rows` 表映射补 `watch_target` / `watch_event`
- 新增 `tests/watch_check.py` 第 1 节（领域 CRUD 往返断言）；`tests/run_all.py` 增加 `watch_check` 段（run_all 变 **6 段**，为 T5 的升级路径 E2E 预留同一模块）。

## Capabilities

### New Capabilities
- `business-watch`: 委托（watch_target）与命中事件（watch_event）的持久化存取契约 —— V4 首个归档 change 建立该能力 spec（本 change 的 delta spec 首次出现，archive 时并入主 spec）。

## Impact

- 后端：`models.py`（+2 模型）、`repository.py`（+CRUD 原语 + count_rows 映射）、`tests/watch_check.py`（新增）、`tests/run_all.py`（+1 段）。
- 不改：引擎、routers、前端、现有 5 段测试行为（golden 9 insights 不受影响 —— 新表不被引擎读取）。
- 验证：`cd backend && python3 -m tests.watch_check`（CRUD 全绿）+ `python3 -m tests.run_all`（6 段 ALL GREEN）+ DB 空表时先建表（`Base.metadata.create_all` 已由 `db.init_db` 兜底）。
