## 1. types 与 doraApi

- [x] 1.1 `types.ts` 增 `CaseStep`/`ActionCaseCard`/`ActionCaseDetail`；`doraApi.ts` 增 `createAction/listActionCases/getActionCase/startStep/doneStep/blockStep/verifyAction`（4xx 显式上抛）；验证：`npm run build`
- [x] 1.2 `App.tsx route`：problem/opportunity → `createAction(id)` 成功后 navigate("action")；4xx notify detail 不跳转；断网才本地 join 演示

## 2. ActionPage

- [x] 2.1 重写：列表=真 cases；选中→getActionCase 详情；步骤按钮（start/done/block）按 status 出；waiting_verify → 验证区（textarea note → 归档 / 继续观察）；resolved → 归档视图（archive 含验证记录）；后端不可用 → demo 兜底（joined×data.ts actionCases 静态，标注离线演示）；验证：build + 页面冒烟

## 3. 收尾

- [x] 3.1 回归：run_all 7 段 ALL GREEN（后端契约不变）；golden 9 不变
- [x] 3.2 dev-log「迭代 31」+ 路线图 §3C V5-T4 标记 + archive（【测试证据】+【反思】）

【测试证据】npm run build ✅（tsc + vite 46 modules）；run_all → ALL GREEN（7 段, golden 9 不变）。页面验证路径：ActionPage 加载 listActionCases → 选 id fetchActionCase 详情 → steps 状态按钮调用 start/done/block → waiting_verify 显示验证区（resolved 归档 / continue）→ resolved 显示归档视图；洞察「加入行动回路」= App.route 调用 createAction（4xx 展示 detail 不伪造、断网回退本地 join demo）。
【反思】旧 doraApi 已有同名 getActionCase（/actions 静态），新函数命名冲突被 tsc 当场抓住 → 新端点函数以 fetch/list/act 前缀避坑；demo/真实双 return 比单组件内 if/else 分支更利于类型收窄；前端视觉从静态时间线简化为通用步骤列表（功能真实优先，时间线美化可后续）。
