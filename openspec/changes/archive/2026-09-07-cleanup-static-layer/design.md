## Context

见 proposal.md。后端静态层曾服务 V1–V3 演示；V4(V5)真实化后它们成了"第二套真实"。删除前须先让 e2e 与前端 sync 不依赖它们。

## Goals / Non-Goals

**Goals:** routers 不再吐静态 /actions、/insights、/evidence 兜底；删死代码；DTO 拆型；e2e 用真实档案断言。

**Non-Goals:** 删除 data.ts 离线演示数据（保留离线兜底语义）；删除 schemas 中闲置模型（低价值噪音，可留）；行为级功能变更。

## Decisions

- **get_insight 只查引擎**：当前引擎已覆盖 p1..o2/c2 等全部 id；不再支持"历史静态 id 仍可读"——查不到即 404（诚实）。
- **evidence 只查 DB**：engine_evidence 生成失败即 404；不再用 EVIDENCE 兜底掩盖缺证据。
- **e2e Case1/2 语义升级**：原 execute 是对"静态行动"的 mock 断言；改为断言真实 seed 档案存在且步骤非空（V5 后执行由步骤按钮驱动，Action 闭环已由 action_check 第 4 节覆盖）。
- **sync 不再拉 /actions**：data.ts actionCases 保持演示原样；ActionPage demo 分支直接读它。
- **F3**：list 摘要无 steps → 明确 ActionCaseCard 类型；详情单独 fetchActionCase。

## Risks / Trade-offs

- 删除 INSIGHTS/EVIDENCE 兜底后，任何引擎新 id 若未配证据/文案 → 404（正确暴露缺口，不再静默）。golden/action_check 已保证现有 9 洞察有文案与证据。
- 旧 /actions 移除是"行为删除"，已在审计文档与 P/D 记录在案。
