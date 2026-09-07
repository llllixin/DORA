## Context

见 proposal.md。后端 T2/T3 已在 `/api/insights` 返回 `reasonSource`/`generatedAt`；前端类型尚未消费。

## Goals / Non-Goals

**Goals:** 详情页展示来源徽标 + "重新解释"按钮，刷新后重同步并提示结果/回退。

**Non-Goals:** 不改判定/语义结构；不做流式对话（另立）；不做批量管理 UI。

## Decisions

- 复用 App 既有同步链路：按钮 → `refreshReasoningApi()` → `syncRemoteData()`（拉取最新含 reasonSource 的洞察）→ `setSyncTick` 强制重渲染 → toast 提示（llm/template/失败回退）。
- 徽标：`reasonSource==='llm'` → Tag(green)「AI 解释」；否则 Tag(ai)「模板解释」；可选 `generatedAt` 置 title 悬浮。
- TS：Insight 可选字段（只读消费，不破坏 data.ts 本地类型）。
