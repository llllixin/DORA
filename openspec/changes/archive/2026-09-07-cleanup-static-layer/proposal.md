# cleanup-static-layer

## Why

全流程审计（docs/优化方向.md，P0-1）发现维护债：V4/V5 已真实化但服务端仍残留静态双源（/actions*、/insights 历史兜底、/evidence 兜底），前端有死代码（createFollowup/executeAction/legacy getActionCase/listActions），Action 列表类型把"摘要当详情"（缺 steps）。本次一次收口，避免"两套真实"再扩散。

## What Changes

- **F1 静态双源下线**：
  - `routers.py`：移除 `/api/actions` list/get/execute 静态端点、`/insights/{id}` 的 INSIGHTS 历史兜底分支、`/evidence/{id}` 的 EVIDENCE 兜底；删除 `from app.data import …`（不再被 routers 引用）。
  - `tests/e2e_api_check.py` Case1/2 改为用真实档案断言（GET /action/cases 含 p1/o1 且步骤非空），不再依赖静态 execute。
  - 前端 `syncRemoteData` 不再拉旧 `/actions`（data.ts 演示数据保持原样供离线 demo）。
- **F2 死代码**：删除 `doraApi` 的 `createFollowup`/`executeAction`/旧 `getActionCase`/`listActions`（无调用点；Action 真路径已用 fetchActionCase 等）。
- **F3 DTO 拆型**：`types.ts` 增 `ActionCaseCard`（无 steps 的列表摘要）；`doraApi.listActionCases` 返回 `ActionCaseCard[]`；ActionPage 列表态/详情态分离。
- **F10**：`.env.example` 补 DeepSeek 官方注释样例（与本地实际配置对齐说明）。

## Capabilities

- 无 spec 变更（skip_specs）：删除的是演示静态层，真实契约（/action/cases 等）不变。

## Impact

- 后端：routers.py、tests/e2e_api_check.py；前端：types/doraApi/App/ActionPage；docs：.env.example。
- 验证：run_all 7 段 ALL GREEN（e2e Case1/2 用真实档案）；npm build；离线冒烟仍走 data.ts demo。
