## Context

见 proposal.md。后端 /api/action/cases REST 已就绪（T3）；ActionPage 现为静态 data.ts 单行 JSX。T4 换成真数据驱动、尽量复用现有 card/btn/Tag 样式。

## Goals / Non-Goals

**Goals:** 前端真消费（列表/详情/步骤/验证/归档）；洞察建档入口真调用；离线回退演示。

**Non-Goals:** 旧 /actions 静态端点下线（T5 随 e2e 切换）；Pulse 改动（洞察/关注计数已真实）；AskBar/专家增补等编排编辑（沿用静态展示）。

## Decisions

- **新页面读 detail 直渲 steps**（不再依赖旧 5 段 Timeline 静态假设）：`steps.map` 显示每步状态徽标与 note/result，按 step.status 出按钮；不同步改旧 ActionCase 类型。
- **App.route 语义升级**：problem/opportunity 点击 → `createAction(id)`；成功（created True/False）通知并跳转；后端 4xx（detail）→ notify 错误不跳转（不伪造）；纯网络失败（断网）→ 旧演示路径（本地 joined + data.ts 兜底）。
- **ActionPage 数据源**：挂载时 `listActionCases()`；空/失败 → demo 兜底。选中 id 拉 `getActionCase(id)`；每次动作后重拉该详情。
- createAction 复用"4xx 上抛、断网回退"模式（与 createWatch 相同），服务端错误文案直接展示。

## Risks / Trade-offs

- 页面视觉从"精致静态时间线"退化为"通用步骤列表"（一步到位的时间线美化留后）→ 功能真实优先；CSS 复用现有 card/btn/Tag。
- demo 兜底与真数据并存逻辑在组件内 if/else → 有限、可维护。
