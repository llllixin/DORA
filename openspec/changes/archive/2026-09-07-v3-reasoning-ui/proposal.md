## Why

V3 后端已能生成/缓存 LLM 或模板解释，但页面没有入口与来源展示。T4 把"重新解释"与"来源徽标（AI / 模板）"加进洞察详情，让用户可见并可主动刷新。

## What Changes

- `doraApi.refreshReasoningApi()`（三模式；mock 回退本地成功对象）。
- `types.ts`：Insight 增加只读 `reasonSource?: "template"|"llm"`、`generatedAt?: string`。
- `App`：提供 `onRefreshReasoning`（调 refresh API → 重新同步引擎数据 → 通知结果/回退提示）。
- `InsightPage`：详情头部显示来源徽标（AI 解释/模板解释）+ "↻ 重新解释"按钮（busy 态），刷新成功后重渲染。

## Capabilities

<!-- 纯前端展示/交互，消费后端既有 reasonSource/generatedAt，skip_specs: true -->

## Impact

- 前端：`doraApi.ts`、`types.ts`、`App.tsx`、`features/insight/InsightPage.tsx`。
- 验证：`npm run build` + 冒烟 + 后端无改动（run_all 仍绿）。
