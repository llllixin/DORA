# fix-reason-refresh-timeout

## Why

P011/Bug1（分析阶段即标记"前端 refresh timeout 2600ms 会误杀"）在接真实 LLM 后兑现：`refreshReasoningApi` 走 `apiPost` 默认 2600ms，而 llm 批量实测 ~5s（预算内）→ 前端必然 abort，`App.refreshReasoning` catch → 每个 problem 点击「重新解释」都 toast「解释刷新失败，已保持模板解释」（后端其实继续跑完并已写 llm 缓存，UI 自相矛盾）。

## What Changes

- `frontend/src/services/doraApi.ts`：`refreshReasoningApi` 显式传 `timeoutMs = 30000`（覆盖默认 2600ms），与后端"预算 20s + 在途尾差"上界对齐（余量防网络抖动）。
- 附注：后端并发单飞已保证连点合并为一次执行；30s 只防误杀不放大负载。

## Capabilities

- 无 spec 变更（skip_specs）。

## Impact

- 仅前端一处调用参数；验证：`npm run build`；真实 DeepSeek 环境「重新解释」不再 2.6s 假失败（run_all 不受影响）。
