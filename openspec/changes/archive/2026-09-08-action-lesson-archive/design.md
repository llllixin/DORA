## Context

见 proposal.md。V5 档案已含 archive（含 verify 记录）。本 change 加"沉淀入口 + 经验表 + 布局重构"。

## Goals / Non-Goals

**Goals:** resolved→一键沉淀 CaseLesson；GET lessons；ActionPage 抽屉布局（列表小、流程大）+ 归档后处理过程视图与经验展示。

**Non-Goals:** 训练/微调模型（经验=确定性记录，未来引用由规则/检索做，D033）；SSE；批量经验导出。

## Decisions

- **CaseLesson 结构**：case_id(pk 幂等)/code/kind/title/archive(处理过程全文)/resolution(note)/created_at；create-if-absent 天然幂等。
- **沉淀权限**：仅 resolved（复用一个 guard）；note 必填（沉淀必须有结论，否则 400）。
- **布局**：ActionPage 左侧列表改抽屉（宽度可收，折叠为竖向 code tab），主区最大化放流程/验证/归档；归档区双动作：查看处理过程 + 沉淀经验。
- **经验库 UI**：抽屉底部"学习经验 n"切换显示最近经验（问题/处理/结论）——先做查看，不做相似推荐（未来引用留后续，属 D033 边界）。
- skip 不必：本 change 有 spec delta（见 specs）。

## Risks / Trade-offs

- "自我学习"措辞克制为"确定性沉淀+检索"，不夸大；经验条数由用户操作产生，seed 不制造假经验。
- 布局改动涉及 ActionPage 大改 → 保持 demo/真实双逻辑不回归（build+run_all 守门）。
