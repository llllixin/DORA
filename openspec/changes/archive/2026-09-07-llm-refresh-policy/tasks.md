## 1. 策略层

- [x] 1.1 `app/reasoning/policy.py`：env 参数读取（timeout=10/budget=20/concurrency=3/fails=3/window=60/cooldown=30）+ `DegradationError`/`CircuitOpenError` + 线程安全 `CircuitBreaker(now=None)`（窗口滑动、record_failure/record_success/is_open、注入 now 可测）+ `is_degraded(exc)` + `priority_key(insight)`；验证：reasoning_check 单测（见 1.3）
- [x] 1.2 `llm.py`：超时参数 40→`policy.timeout_secs()`；调用前 `breaker.is_open()` → 抛 `CircuitOpenError`；网络降级捕获→`record_failure`→抛 `DegradationError`；成功 `record_success`；本地/解析错误不动 breaker；验证：真实 DeepSeek 冒烟仍 200 语义（不引门禁）
- [x] 1.3 `cache.py` refresh 重写：template 串行原语义；llm 走调度（排序→ThreadPool 并发 2–3→提交前查预算/熔断/连续失败≥3→在途收尾）；返回契约不变；验证：无 key fallback 仍全量（配置错不触发中止）
- [x] 1.4 `routers.py` reason_refresh 单飞（Condition：并发请求合并等待同结果）；验证：并发两请求 curl，后端只执行一批（日志 updated 相同）

## 2. 测试与收尾

- [x] 2.1 `tests/reasoning_check.py` 补：CircuitBreaker 注入时钟（失败窗口计数→open→cooldown 后恢复、success 重置、is_open 判定）、priority_key 排序、无 key fallback 全量断言保持；`python3 -m tests.reasoning_check` ALL GREEN
- [x] 2.2 回归：`python3 -m tests.run_all` 6 段 ALL GREEN；golden 9 不变
- [x] 2.3 `.env.example` 补策略变量注释；dev-log「迭代 27」+ D 系列补 D030（urllib 无独立 connect 超时的取舍记录 + 阶段 1 退出条件） + archive（【测试证据】+【反思】）

【测试证据】reasoning_check → "reasoning_check OK (parity 9; T2 cache merge OK; policy OK)"（熔断注入时钟/优先级/降级分类）；run_all → ALL GREEN（6 段, golden 9 不变）；真实 DeepSeek：批量 refresh 9/9 updated、总耗时 4.9s（并发 3、预算内, 串行时代 15.6s）；并发单飞冒烟：两请求 wall 5.4s 都返回 9 updated（仅执行一批）→ updated 顺序即优先级 p1→o1→c1。
【反思】urllib 只有单一 socket 超时，无独立 connect/read 拆分 → 以总超时 10s 实现（取舍记 D030）；HTTPError 是 URLError 子类，降级分类必须先判 HTTP 再判 URLError（单测当场抓住 400 误判 bug）；无 key/解析错误不计熔断，避免配置错把整批熔掉；单飞仅进程内（多进程部署前需外部协调）。
