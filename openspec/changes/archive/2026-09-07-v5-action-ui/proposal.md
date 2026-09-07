# v5-action-ui

## Why

V5-T1..T3 已有档案/建档/状态机 REST，但 Action 页仍读 data.ts 静态。T4 把页面接到真数据：ActionPage 显示 DB 档案列表/详情（steps 状态机按钮真实调用 start/done/blocked/verify），洞察页「加入行动回路」从假本地通知改为真建档（离线才回退演示）。Pulse 无需改（洞察/关注计数已真实）。

## What Changes

- types：`CaseStep`/`ActionCaseCard`/`ActionCaseDetail`（对齐 /api/action/cases 形状）。
- doraApi：`createAction(insightId)`、`listActionCases()`、`getActionCase(id)`、`startStep/doneStep/blockStep`、`verifyAction`；业务 4xx 显式上抛不静默 mock。
- App.route：problem/opportunity → 真建档（HTTP 4xx 显示错误；断网才走本地演示 join）。
- ActionPage 重写：列表（来自真 cases）→ 详情（steps 状态/note/result、start/done/block 按钮、waiting_verify 时验证区 note→归档/继续、resolved 归档视图）；后端不可用时回退本地静态演示并标注。

## Capabilities

### Modified Capabilities
- `business-action`: 档案可在界面真实执行与验证（按钮驱动 start/done/blocked/verify），洞察页可从引擎判定建档入口进入档案。

## Impact

- 前端：types/doraApi/App/ActionPage；后端零改动（REST 已就绪）。
- 验证：npm run build；run_all 7 段 ALL GREEN（后端契约不变）；页面冒烟（建档→推进→归档走 API）。
