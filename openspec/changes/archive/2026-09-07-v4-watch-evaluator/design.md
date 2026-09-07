## Context

见 proposal.md。T1 的 watch_event 有 kind=change|escalate、summary、values{prev,cur}；T2 的 condition 结构 {type,days,ref,ref_is_pct}。T3 只需"解读它 + 定时跑它"。引擎已提供：run_engine()（含 east 跌破→problem e2 的真实升级链路）、_mean、_pct。不新增依赖。

## Goals / Non-Goals

**Goals:** 条件求值（时间序列口径复用引擎数据，不重算口径）+ 命中/升级事件（带去重）+ 数据更新即时触发 + 每日/每周进程内调度 + touch last_checked_at。

**Non-Goals:** /api/watch CRUD 与前端（V4-T4）；Case 3/4 端到端 HTTP E2E（V4-T5）；WatchEvent 分页/裁剪；多进程调度（单实例守护线程，D009 Redis/Celery 仍推迟）。

## Decisions

- **求值口径与引擎一致**：值全部来自 `repo.get_series(key)`（引擎同源）；dimension=="" 时按"同一 label 周期跨维度聚合（均值）"构造时间线（returns 门店级即此类），口径在 T2 design 已预告、在此落实。
- **streak 语义 = 日环比**：从时间序列尾部数"逐点下降"连续天数（下降指 v[i] < v[i-1]，严格）；上涨对称。below/above = 最新聚合值对比 ref（ref_is_pct 仅标记，单位与序列一致时直接数值比较）。
- **升级不伪造（红线）**：仅 `ESCALATION = {margin:p1, returns:p2, orders:p3, aov:o1, east_orders:e2}` 且 run_engine 本次确实产出该 insight 时，事件 kind=escalate + values.engine_insight；engine 没判 → 永远只 change。新_sku/revenue/high_value 等无 problem/opportunity 身份 → 不会 escalate（诚实边界）。
- **去重**：若该 target 最近一条事件 kind+values 与本次相同 → 跳过不写（幂等重评估/重置后不刷屏）；数据真变则新事件。
- **触发接线**：数据写入路径成功后**即时**评估 on_update（辅助逻辑，异常只告警不使上传失败）；周期由单例守护线程每分钟 tick，`_is_due` 纯函数注入 now 便于测试。时间统一 UTC。
- **出厂重置语义补定（T1 遗留）**：sample/seed 重置**保留 watch_target、清空 watch_event**（委托是用户意图不被样例抹掉；事件引用旧数据应清）。本 change 在 sample/seed 重置路径执行 delete_all_watch_events。等 T4/T5 若需调整再改。
- 评估中 run_engine 全量算一次共享给所有 target（≤几毫秒级），避免每 target 各跑一次。

## Risks / Trade-offs

- 求值聚合口径（dimension="" 均值时间线）是我方定义、非引擎既有项 → 用 watch_check 断言固化；未来若引擎加"整表退货率"再对齐。
- 周期调度=单实例内存线程，重启丢失（只丢"到期未跑"，重启后下一次 tick 按 last_checked 补跑）→ 单实例场景可接受，V4 结束前若要多实例再引 Redis。
- 数据更新即时评估里套 run_engine 有额外计算（毫秒级）→ 接受；异常仅告警不影响上传主流程。
