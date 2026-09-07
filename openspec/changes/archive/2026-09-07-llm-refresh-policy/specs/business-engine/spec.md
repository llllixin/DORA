## ADDED Requirements

### Requirement: 洞察刷新在外部推理服务降级时有界有据
系统 SHALL 在 provider=llm 时对单条 LLM 调用设 ≤10s 超时，并对整批刷新设 ≤20s 预算与 2–3 并发：预算用尽后不再发起新调用，未完成洞察进入 `fallback`；连续 3 次网络级降级失败即中止整批、其余全部 fallback；同一进程 60s 窗口连续失败≥3 触发熔断 30s，熔断期间刷新不发起任何外部调用并立即全量 fallback。刷新 SHALL 按 问题→机会→变化 的优先级消费预算。重复的并发刷新请求 SHALL 合并为一次执行（后到者等待同一结果）。

#### Scenario: 供应商慢/挂起时批量刷新有界
- **WHEN** provider=llm 且外部调用持续超时（网络级降级）
- **THEN** 单条在 ~10s 内失败、连续 3 条后整批中止，剩余洞察全部 `fallback`，刷新总耗时不超过预算+在途尾差（≈30s 内），不出现逐条 40s 的分钟级阻塞

#### Scenario: 熔断开启时不再触网
- **WHEN** 熔断处于 open（60s 窗口 ≥3 次失败后的 30s 内）再次 refresh
- **THEN** 不发起任何外部调用，全部 `fallback` 并快速返回（provider 仍标注 llm）

#### Scenario: 并发刷新合并（单飞）
- **WHEN** 两个请求同时调用 `/api/reason/refresh`
- **THEN** 实际只执行一次 LLM 批量（后到者复用首个请求的结果返回）
