## Context

见 proposal.md。现状：llm.py `urlopen(timeout=40)`、cache.refresh 串行、无熔断/单飞。阶段 1 目标 = 有界 + 快失败 + 少打供应商；**不改判定/契约/前端**。

## Goals / Non-Goals

**Goals:** 单条超时 10s；整批预算 20s + 并发 3；降级熔断（3 次/60s → 开 30s）；优先级 问题→机会→变化；并发 refresh 单飞；env 可调；reasoning_check 单测。

**Non-Goals:** 异步任务/状态接口与前端轮询（阶段 2）；Redis/Celery；指数退避重试（单次尝试即 fallback，阶段 1 优先"快"）；每 insight 白名单刷新；prompt 调优。

## Decisions

- **单条超时总包**：urllib 只有单一 socket 超时，无独立 connect/read 拆分 → 统一 `DORA_LLM_TIMEOUT=10`（即含连接+读取），与"connect 应更短"的差异记录在案；如需真拆分再换 http.client（阶段 2 若转 asyncio/httpx 一并解决）。
- **降级分类（熔断只数"供应商问题"）**：URLError/socket.timeout/HTTP 429/5xx = DegradationError（记数）；无 key、401/400、JSON 解析坏 = 一般异常（**不记数**，否则配置错会把熔断打挂全批）。
- **中止规则**：调度循环内"连续降级失败 ≥3"即停排剩余（整批 fallback）；熔断 open 同样停排。
- **预算判定在"提交前"**：提交新 worker 前查 `now-start ≥ budget` → 剩余全 fallback；已在途 worker 等其自然结束（单条 ≤10s），总耗时上界 ≈ 预算 + 在途尾差（2–3 条 × ≤10s ≈ ≤30s 内，纳入 spec 场景）。
- **优先级**：type 排序 problem→opportunity→change（引擎类型稳定，用 type 字段即可，不引 insight 分数）。
- **单飞在 routers 层**：Condition 变量保护：首个请求执行并保存结果，后到请求 wait 到结果直接复用（幂等 upsert 缓存兜底一致性）。
- **并行 upsert**：Repository 方法均为短会话自建 session，线程安全；不在 worker 间共享 session。

## Risks / Trade-offs

- 预算提前耗尽可能使尾部的变化类洞察拿不到 LLM 文案（fallback 模板）→ 正是设计意图（重要优先 + 诚实标注），reasonSource 仍正确。
- ThreadPool + 熔断状态是进程内 → 多 worker 进程各自独立（阶段 2 异步化/集中状态时再收敛）。
- 单飞只在本进程内生效 → 多进程部署时仍需幂等/外部协调（当前单机产品阶段接受）。
