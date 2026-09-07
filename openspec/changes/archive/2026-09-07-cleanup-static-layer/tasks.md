## 1. 后端静态层下线

- [x] 1.1 `routers.py`：删 `/actions` list/get/execute；删 `/insights/{id}` 的 INSIGHTS 兜底循环；删 `/evidence/{id}` 的 EVIDENCE 兜底；去掉 `from app.data import …`；验证：curl /api/actions → 404、不存在 id → 404
- [x] 1.2 `tests/e2e_api_check.py` Case1/2：断言 GET /action/cases 含 p1/o1 seed 且 steps 非空（替换原 /actions execute 断言）；验证：e2e_api_check ALL GREEN

## 2. 前端清理

- [x] 2.1 `types.ts` 增 `ActionCaseCard`；`doraApi`：删 createFollowup/executeAction/旧 getActionCase/listActions 及其对 actionCases import；`listActionCases` 返回 `ActionCaseCard[]`；`syncRemoteData` 去掉 /actions 拉取与 actionCases 覆写；验证：`npm run build`
- [x] 2.2 ActionPage：列表态 `ActionCaseCard[]`、详情态 `ActionCaseDetail`（点击才 fetch）；demo 分支不变；验证：build + 页面冒烟

## 3. 收尾

- [x] 3.1 回归：`python3 -m tests.run_all` 7 段 ALL GREEN；golden 9 不变；npm build
- [x] 3.2 `.env.example` 补 DeepSeek 注释样例（F10）；dev-log「迭代 34」+ archive（【测试证据】+【反思】）

【测试证据】run_all ALL GREEN（7 段, golden 9 不变; e2e Case1/2 改为真实 /action/cases/p1|o1 档案断言）; npm run build ✅; curl：/api/actions → 404、/api/actions/p1 → 404（静态已下线）、/insights?type=problem 200、/action/cases 200、/evidence/p1 200。
【反思】删静态前先改消费方（e2e/sync）再删端点，避免红门禁；get_insight/evidence 现只认引擎判定与 Repository 生成（缺则 404 暴露缺口而非静默兜底）；Action 列表=ActionCaseCard 摘要、详情=ActionCaseDetail，拆型消除"摘要冒充详情"；data.ts 仅离线演示语义清晰。

