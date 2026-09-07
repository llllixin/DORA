## Context

见 proposal.md。根因：apiPost 默认 2600ms 与真实 LLM 批量（实测 ~5s、预算 20s+尾差）不匹配；前端 abort 走 fallback（ok/模板），后端其实完成并写缓存 → UI 自相矛盾且反复 toast 失败。

## Goals / Non-Goals

**Goals:** refreshReasoningApi 显式 30s 超时（对齐后端预算上界+余量）。

**Non-Goals:** 前端异步轮询/状态跟踪（阶段 2）；改其它 apiPost 调用；后端改动。

## Decisions

- 30s = 后端预算 20s + 并发尾差(≤10s) + 抖动余量；并发单飞在后端保证连点不放大负载。
- 仅此一处覆盖默认值，避免全局放宽掩盖其它快接口误用。

## Risks / Trade-offs

- 若 LLM 供应商极慢超 30s 仍会超时 → 阶段 2 异步化才是终态；本修复先消除误杀。
