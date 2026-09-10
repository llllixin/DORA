## Context

动机与范围见 proposal.md。技术现状（决定本设计的事实）：

- InsightPage 消费 `insights[type]`（D008 原位同步数组）：后端在线时是 `/api/insights` 引擎行（每行含 `semantics{causeA,causeB,next}`、`trigger`、`factors`、`reasonSource`）；离线时是 `data.ts` 镜像。
- 引擎 `semantics` 现覆盖全部 9 个 demo 洞察（默认模板缓存即有）；`data.ts` 镜像中 **p1–p3 已由 W1 补齐 semantics，o1/o2/c1–c4 仍缺**。
- 当前 InsightPage 用 `x.semantics` 当有；无 semantics 时回退到组件内按 id 的 `next/cause/n` **写死字典**（本 change 要删除的静态双源）。
- 图表卡 `InsightChart data={chartData[x.id]}` 仍是前端静态（F11，明确非目标）。
- AskBar / FollowupCard「追问」入口为占位（F8，不夹带）。

## Goals / Non-Goals

**Goals:**
- InsightPage 不再出现任何"非来自该洞察字段"的写死归因/建议；cause/next 只消费 `semantics`。
- 无 semantics 时有显式降级文案（模板未覆盖 / 下一步暂无），不编造数字、不编造步骤。
- 离线镜像（data.ts 9 洞察 semantics）补齐，删字典后停后端冒烟与现状 demo 观感一致。
- AskBar / 路由 / 建档入口行为不变（不夹带 F8）。

**Non-Goals:**
- F8 追问真实化；F11 图表引擎驱动（均另立候选）。
- 数据刷新/轮询机制（W3 统一）；Pulse 其它面板（W1 已归档）。

## Decisions

### D1 cause/next 只来自引擎 semantics；缺省显式降级
`causeA/causeB/nA/nB` 直接读 `x.semantics`；`nxt` 读 `x.semantics.next`。无 semantics 时：归因两卡不渲染伪造值，改在原因区显示 note「模板未覆盖该洞察的可视化归因；以下为引擎原文字段」，并展示 `desc/question/factors/trigger`（有则显示）；下一步建议显示「暂无引擎建议」空态。
- 为什么：`business-engine` 契约保证 semantics 由 reasoning（模板/LLM）下发且不污染判定；前端不再需要 id 级字典兜底。
- 备选：保留字典仅当 id 存在时用 → 真数据集会显示错配文案，否决。

### D2 离线镜像迁移：9 洞察全部补齐 semantics（审查补强 1）
`data.ts`：为 o1/o2/c1–c4 补 `semantics`（causeA/causeB/next 取自已删的写死文案语义），并校验 p1–p3 已存在；顶部注明「离线演示镜像」。删除组件字典与补齐镜像必须同 change（删字典 ≠ 离线空壳）。
- 为什么：InsightPage 与 Pulse 离线都消费同一镜像；缺失则删字典后离线只剩空卡。
- 备选：离线保留旧字典、仅在线用 semantics → 双源仍在，违背本 change 目的，否决。

### D3 字段盘点固化（审查补强 2）
在 InsightPage 代码头注释维护「面板 → 所需字段 → 来源 → 降级文案」表（归因卡=semantics；原因区=desc/question/factors/trigger；下一步=semantics.next；图表=F11 静态注明），使来源可查、防再次写死。
- 为什么：承接 W1 的字段盘点做法，杜绝静态回归；图表静态事实在注释里显式暴露而非假装。

### D4 保持 AskBar/Followup 与路由行为
「生成行动/加入行动回路」按钮、FollowupCard、AskBar 均不改（F8 追问仍是占位提示），重构只动数据来源相关 JSX。
- 为什么：F8 属另立候选；W2 是静态双源清理，不夹带能力。

## Risks / Trade-offs

- [离线镜像语义是演示叙事，可能与引擎实时语义不一致] → 仅离线态展示，data.ts 顶部标注；在线只认 `/api/insights` semantics。
- [删除字典后离线视觉变化] → 同 change 补齐镜像 + 人工离线冒烟验收（任务 3.x）。
- [个别引擎行某字段（如 factors）缺失时空态文案突兀] → 用条件渲染 + 通用缺省，不产生假值。
- [图表仍静态（F11）可能让"图表与正文不同源"观感残留] → 本 change 注释明确非目标并在提案声明，避免静默。

## Migration Plan

- 纯前端：改 InsightPage → data.ts 补镜像 → build → 在线/离线双态冒烟。回滚：`git revert` 该 change 提交（后端零改动）。
- 无 DB/契约/数据迁移。

## Open Questions

1. 无 semantics 时下一步建议的空态文案与样式：默认用「暂无引擎建议（数据/推理刷新后可重试）」+ 复用现有"重新解释"按钮触发刷新。若评审希望更醒目样式可再调（不影响 spec/task 结构）。
