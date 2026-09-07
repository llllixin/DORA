# v4-watch-evaluator

## Why

V4-T1/T2 建好了持久化与解析，但没有"谁在何时判定是否命中"。T3 让委托真正被评估：复用引擎时间序列口径把 watch condition（连续 N 天降/涨、跌破/超过 X）算成命中/未命中，命中写 `watch_event`；并让评估在两处自动触发（数据更新即时 + 进程内周期 tick 每日/每周）。**升级不伪造**：只有引擎已判定该指标为 problem/opportunity（如 east_orders → e2）时才出 `escalate` 事件并引用引擎 insight id。

## What Changes

- `app/watch/evaluator.py`：
  - `_chrono_values`：单 dimension 直取有序值；dimension=""（整表聚合，如 returns 门店级）按 label 同周期聚合成时间线。
  - `_eval_condition`：streak_below/streak_above（日环比连降/连涨）与 below/above（最新值 vs ref）。
  - `evaluate_one(repo, target, engine_insights)` → `{hit, kind: change|escalate|miss, event?, skipped?}`；重复事件（同 kind+values）不重复写；escalate 仅当 `ESCALATION[key]=insight_id` 且 run_engine 中存在该 insight（values 带 `engine_insight`）。
  - `evaluate_all(repo, freqs=(on_update,))`：对 watching 目标批量评估（run_engine 只跑一次共享）；返回计数。
- `app/watch/scheduler.py`：单例守护线程每 60s tick，按 frequency（daily 09:00 / weekly）判断到期目标并评估；`_is_due(target, now)` 纯函数可注入时间单测。
- 触发接线：`POST /api/datasets`、`/datasets/mapped`、`/datasets/sample` 成功后调用 `evaluate_all(on_update)`（异常仅告警不使上传失败）；FastAPI lifespan 启动 scheduler。
- Repository 增 `touch_watch_target(id, checked_at)`（更新 last_checked_at）。
- watch_check 第 3 节「评估器」断言 + 恢复出厂；run_all 仍 6 段。

## Capabilities

### Modified Capabilities
- `business-watch`: 委托按条件被自动评估并记录命中事件；命中不伪造身份——`escalate` 事件只出现在引擎已判定 problem/opportunity 的指标上并引用该洞察。

## Impact

- 后端：`app/watch/evaluator.py`、`app/watch/scheduler.py`、`repository.py`（touch）、`routers.py`（3 处触发）、`main.py`（lifespan）、`tests/watch_check.py`。
- 引擎零改动（只读 `run_engine`/`_mean`）；east 升级链路回归由 run_all/golden 守护。
- 验证：watch_check 第 3 节（命中/未命中/升级引用/幂等去重/恢复）；run_all 6 段 ALL GREEN。
