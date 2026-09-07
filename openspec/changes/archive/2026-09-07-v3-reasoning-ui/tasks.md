## 1. API 与类型

- [x] 1.1 `doraApi.refreshReasoningApi()`（POST /reason/refresh，三模式），验证：`npm run build`
- [x] 1.2 `types.ts` Insight 增加可选 `reasonSource`/`generatedAt`，验证：类型检查通过

## 2. 页面入口与徽标

- [x] 2.1 `App` 增 `onRefreshReasoning`（refresh→sync→重渲染→toast）并传给 InsightPage，验证：build + 冒烟
- [x] 2.2 `InsightPage` 详情头部来源徽标 + "↻ 重新解释"（busy 态），验证：build + 手测（template 模式 toast/徽标）

## 3. 回归与文档

- [x] 3.1 `python3 -m tests.run_all` 全绿（后端未动）+ `npm run build` + 冒烟
- [x] 3.2 dev-log 迭代 + 路线图 V3-T4 标记 + `docs/开发问题与经验.md` D026
