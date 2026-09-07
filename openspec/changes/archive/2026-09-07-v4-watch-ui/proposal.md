# v4-watch-ui

## Why

V4-T1..T3 后端已有委托持久化、解析、评估/调度，但没有把真实数据接回界面。T4 补齐两件事：① 后端 watch REST（create/list/detail/pause/delete/check），否则前端无真实数据可消费；② Watch 页与 Pulse「持续关注」真实化——输入经 parse 回显确认后创建、列表来自 DB、支持暂停/恢复/删除/手动检查，命中事件回到 Pulse 计数与状态。

## What Changes

- 后端 watch REST（`routers.py` + `schemas.py`）：
  - `GET /api/watch`：DB 委托列表转 WatchItem 卡片（name=业务目标、value=最新状态、color 按状态、logic=条件+频率+最近事件、source=口径），旧静态端点移除。
  - `POST /api/watch`：`{text, frequency?}` → parse（unsupported → 400 detail）→ create → 创建后即时评估一次。
  - `GET /api/watch/{id}`：target + 事件列表。
  - `PATCH /api/watch/{id}` `{status}`；`DELETE /api/watch/{id}`；`POST /api/watch/{id}/check` 手动评估一次。
- `evaluator.evaluate_one`：单目标调用时无共享 insights → 惰性 `run_engine` 一次（否则单查/check 会漏升级判定）。
- 前端：
  - types：`WatchItem` 增可选 `status/frequency/lastEventAt`。
  - doraApi：`parseWatch`/`createWatch`/`setWatchStatus`/`deleteWatch`/`checkWatch`（POST/PATCH/DELETE 带超时）。
  - WatchPage：输入→parse 回显真实 intent→确认创建；目标列表来自 `/api/watch`（名称/状态/关注逻辑/操作：暂停·恢复·删除·手动检查）；chips 仍是 6 个常用目标（库存周转会被 parse 拒绝并提示）。
  - Pulse：「持续关注」计数来自真实列表；监控侧卡文案去静态声明。

## Capabilities

### Modified Capabilities
- `business-watch`: 委托经 REST 可被创建/查询/暂停/删除/手动检查；Watch 页与 Pulse 呈现真实委托与命中状态（离线时前端回退本地演示数据并标注静态）。

## Impact

- 后端：`routers.py`、`schemas.py`、`watch/evaluator.py`（惰性 run_engine）、`app/data.py` 的静态 WATCH 退出端点（前端 data.ts 仍作离线兜底）。
- 前端：`types.ts`、`services/doraApi.ts`、`features/watch/WatchPage.tsx`、`features/pulse/PulsePage.tsx`。
- 验证：`npm run build`；run_all 6 段 ALL GREEN；端点冒烟（parse→create→list→pause→check→delete）；WatchPage/Pulse 无 TS 错误。
