## Context

`.action-layout` 遗留自旧双卡 Action（左卡片 1.65fr + 右编排 1fr）。新结构要求"档案入口窄、流程主区宽"，不能复用该 grid。

## Goals / Non-Goals

**Goals:** 抽屉窄列 + 主流程 flex 占满剩余。

**Non-Goals:** 改 demo 分支；改旧 `.action-layout` 样式（其它页面/旧结构不再用，避免误伤）。

## Decisions

- 真实布局内联 flex 容器；抽屉宽度过渡 0.18s；主卡片 flex:1 + minWidth:0（防长内容撑破）。
- 移动端不做专门抽屉适配（当前阶段桌面优先，留后）。

## Risks / Trade-offs

- 与 legacy CSS 解耦意味着未来若有人再用 `.action-layout` 不生效——已注释语义，demo 分支仍用 `.card`。
