## 1. 评估器

- [x] 1.1 `app/watch/evaluator.py`：`_chrono_values`（单 dim 直取 / dimension="" 按 label 均值聚合时间线）、`_eval_condition`（streak_below/above 日环比 + below/above 最新值）、`evaluate_one`、`evaluate_all(repo, freqs=("on_update",))`（run_engine 共享一次；escalate 仅在 `ESCALATION` 命中且引擎有该 insight；去重最近事件 kind+values）；验证：见 watch_check 第 3 节
- [x] 1.2 `app/watch/scheduler.py`：`_is_due(target, now)`（daily 09:00 / weekly；last_checked_at 防重复）+ 单例守护线程每 60s tick（启动时也补跑一次）；验证：_is_due 注入 now 的单测（当日未到期/到期/已跑过）
- [x] 1.3 `repository.py` 增 `touch_watch_target(id, checked_at)` 与 `delete_all_watch_events()`；`main.py` lifespan 启动 scheduler；`routers.py` 在 /datasets、/datasets/mapped、/datasets/sample 成功后即时 `evaluate_all(on_update)`（异常仅告警）；sample/seed 重置路径先清空 watch_event（保留委托）
- [x] 1.4 `tests/watch_check.py` 第 3 节「评估器」：构造连续下跌 margin/东华序列→命中 change；重复评估去重；engine 产出 e2 时 escalate+engine_insight 引用；高值未命中；结束 run_seed 恢复；`python3 -m tests.watch_check` ALL GREEN

## 2. 收尾

- [x] 2.1 回归：`python3 -m tests.run_all` 6 段 ALL GREEN；golden 9 不变；冒烟（upload/sample 后 watch 评估告警无、事件表行为正确）
- [x] 2.2 dev-log「迭代 24」+ 路线图 §3B V4-T3 标记 + archive（【测试证据】+【反思】）

【测试证据】watch_check（第 1–3 节）→ "watch_check OK（第 1 节 CRUD + 第 2 节 解析 + 第 3 节 评估器 全绿）"；run_all → ALL GREEN（6 段，golden 9 不变）；冒烟：uvicorn 以 lifespan 启动 scheduler、/api/datasets/sample 200（counts 58/10/1/6）无评估告警。
【反思】求值口径必须与引擎同源（repo.get_series + _mean），dimension="" 的"按 label 跨维度均值聚合时间线"是本 change 自定义口径，watch_check 固化之（未来引擎加整表口径需对齐）；升级引用引擎 insight id（ESCALATION 白名单）是"不伪造身份"红线的代码化；重复事件去重（kind+values 比对最近事件）让重置/重复评估幂等；出厂重置语义补定：保留委托、清事件（sample 路径 delete_all_watch_events）；数据写入即时评估包 try/except 只告警不阻塞上传主流程。
