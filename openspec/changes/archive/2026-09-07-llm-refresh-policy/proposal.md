# llm-refresh-policy

## Why

V3 已知问题 P011/D028（阶段 1，纯后端）：refresh 目前逐条 `urlopen(timeout=40)` 串行同步，最坏外部故障 ≈ N×40s 阻塞分钟级，且并发重复点击会打爆供应商。阶段 1 落地：**响应有上界**（整批预算 20s + 单条 ≤10s + 并发 2–3）、**供应商故障快速隔离**（熔断：60s 窗口连续失败≥3 → 开 30s，期间不触网）、**预算给重要洞察**（P1 问题→机会→变化）、**连点合并**（单飞）。判定/数值红线不变（LLM 仍只动文案，value 锁基线）。

## What Changes

- `app/reasoning/policy.py`（新）：参数（env 可调：`DORA_LLM_TIMEOUT=10`、`DORA_LLM_BUDGET_SECS=20`、`DORA_LLM_CONCURRENCY=3`、`DORA_LLM_CIRCUIT_FAILS=3`、`DORA_LLM_CIRCUIT_WINDOW=60`、`DORA_LLM_CIRCUIT_COOLDOWN=30`）+ 线程安全 `CircuitBreaker`（注入 now 可测）+ `DegradationError`/`CircuitOpenError` + 降级分类 `is_degraded(exc)` + 优先级排序 helper。
- `app/reasoning/llm.py`：单条 socket 总超时 40 → **10s**（urllib 无独立 connect 超时，总超时即含连接，记录在 D）；每次调用前查熔断（open → 快速 `CircuitOpenError`）；网络降级（超时/URLError/5xx/429）→ `record_failure` 并包成 `DegradationError` 抛出；成功 `record_success`；本地/解析类错误（无 key、坏 JSON）**不计**熔断（避免配置错被当成故障熔掉全批）。
- `app/reasoning/cache.py`：`refresh` 重写为 **带预算/并发/熔断/优先级** 的调度：
  - 优先级：problem → opportunity → change；
  - 并发 2–3（`ThreadPoolExecutor`），预算到点不再提交新条，未提交/未完成的剩余条全部 fallback（部分结果语义已有）；
  - 连续降级失败 ≥3 → 中止整批，剩余 fallback（外部大概率挂）；
  - template provider 路径保持串行原语义（毫秒级，不进线程）。
- `routers.py`：`reason_refresh` 加**单飞**（并发请求合并：后到者等待首请求结果，不重复打 LLM）。
- `.env.example` 补策略变量注释。`reasoning_check` 补熔断/优先级单测（不引网络）。

## Capabilities

### Modified Capabilities
- `business-engine`: 洞察刷新在外部推理服务降级时须有界有据——响应时间有预算上界、供应商故障熔断后快速回退、重要洞察优先、重复刷新合并（刷新仍幂等、fallback 语义与 reasonSource 标注不变）。

## Impact

- 后端：`reasoning/policy.py` 新增、`llm.py`、`cache.py`、`routers.py`、`.env.example`、`tests/reasoning_check.py`。
- 前端零改动（返回契约 `{ok, updated, fallback, provider}` 不变）。
- 验证：reasoning_check（新增熔断注入时钟单测 + 优先级单测 + 无 key fallback 全量不变）；run_all 6 段 ALL GREEN；真实 DeepSeek 冒烟（模板门禁仍钉死 template/空 key）。
