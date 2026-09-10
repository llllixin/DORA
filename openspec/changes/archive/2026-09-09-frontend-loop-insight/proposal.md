## Why

W1（frontend-loop-pulse，迭代 39）已把 Pulse 去静态；Insight（洞察详情页）仍是 **前端静态回退字典的下一个重灾区**：`cause1/cause2/n1/n2/next` 等按洞察 id（p1…c4）在组件内**写死**了归因名、数值与"下一步建议"——后端已由 reasoning 下发结构化 `semantics`（D015），但这些写死字典在真实数据集（无 p1…c4 这些 id）下会显示**与该洞察引擎字段无关的文案**，违反"前端只表达后端判断、判断不残留页面"。本 change 收口 3D.1-W2。

## What Changes

- **InsightPage 静态回退字典下线**：删除组件内按 id 写死的 `next[p1..c4]`、`cause1/cause2`、`n1/n2` 字典与 `x.id==='pN'` 分支；cause/next 只消费引擎下发的 `x.semantics`（reasoning 缓存/模板，含 causeA/causeB/next）。
- **无 semantics 的降级诚实**：某洞察无 semantics 时，归因区显式显示「模板未覆盖该洞察的可视化归因」note，并只展示引擎原文字段（desc/metric/delta/source/question，若有 factors/trigger 一并展示）；"下一步建议"显示空态文案——**不编造任何数字/步骤**。
- **离线镜像迁移（审查补强 1）**：`data.ts` 为 9 个 demo 洞察（p1–p3/o1/o2/c1–c4）补齐结构化 `semantics`（causeA/causeB/next，等价于被删的写死文案），保证删字典后离线 demo 观感与现状一致（p1–p3 已由 W1 补齐，本 change 校验并补 o1/o2/c1–c4）。
- **字段盘点（审查补强 2）**：Insight 各面板所需展示字段 ↔ 来源（`/api/insights` 同步结构的 `desc/semantics/trigger/factors/question` 或 `data.ts` 镜像）↔ 降级文案 映射固化进代码头注释。
- **范围边界**：AskBar/FollowupCard「追问」仍是占位提示（F8 另立，**不夹带**）；图表仍为前端静态 chartData（F11 另立）。

**迁移/兼容说明**：纯前端行为收敛到既有引擎契约；后端与 API 零改动。在线真实数据若引擎已给 semantics（默认模板+LLM 均有）则展示不变或更准；无 semantics 的旧镜像数据由离线迁移补齐。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
（无 spec 需求变化。insight 的归因语义契约已由 `business-engine` 既有需求「洞察语义可来自推理缓存并标注来源 / LLM 解释可配置且不污染判定」覆盖；本 change 是把 InsightPage 前端实现向该契约收敛的接线/清理，不改任何系统对外行为 → `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **前端**：`frontend/src/features/insight/InsightPage.tsx`（删写死字典 + semantics 驱动 + 无 semantics 降级）；`frontend/src/data.ts`（o1/o2/c1–c4 补 semantics 离线镜像）；代码头注释字段盘点表（或收敛到一个轻量 helper）。
- **后端/DB**：无改动。
- **依赖**：无新增。
- **验证**：`cd frontend && npm run build`；静态 grep（写死 next/cause 字典无命中）；esbuild 离线镜像断言（9 洞察均有 semantics 或显式降级）；后端在线/离线页面双态冒烟（人工）；后端 `run_all` 不回归（零改动仍跑一次确认）。
