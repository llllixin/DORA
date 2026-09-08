# fix-action-layout-flex

## Why

迭代 36 抽屉化后用户反馈"流程主区没变大"。根因：ActionPage 仍把抽屉+主区放进 CSS class `.action-layout`——它是旧 Action 页的 **grid(1.65fr/1fr)**，于是抽屉被当左列占 1.65fr、主流程区被塞进 1fr 小列，比例与改前几乎一致。

## What Changes

- ActionPage 真实布局改用 **flex 容器**（`display:flex; gap:14`）：抽屉定宽（开 300 / 收 60、flexShrink:0、带过渡），主区 `flex:1; minWidth:0` 占据剩余大部分。
- demo 离线分支保持不变。

## Capabilities

- 无 spec 变更（skip_specs）。

## Impact

- 仅 `frontend/src/features/action/ActionPage.tsx` 布局容器；验证 `npm run build`。
