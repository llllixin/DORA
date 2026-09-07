## Context

见 proposal.md。F4 根因：run_seed 对 5 个静态 seed 档案做 upsert_seed_case（整档案重建），覆盖用户推进的步骤状态/note 与 verify 追加的 archive 行。改为"仅缺省建档"，出厂重置恢复的是数据（metric/watch 事件），不是用户已推进的行动档案。

## Goals / Non-Goals

**Goals:** seed 建档幂等且不覆盖进度；真实 LLM 冒烟脚本；20s 轮询；F9 核对记录 + F11 登记。

**Non-Goals:** SSE/正式推送（阶段 2）；Chat 追问（F8 候选）；图表引擎化（F11 候选，另立）；改 run_all 段数。

## Decisions

- **F4 语义（记 D032）**：样例/出厂重置 = 数据回到出厂；**行动档案（含 5 个 seed 演示档案）一旦被推进，不再被 sample 覆盖**（尊重"结果决定关闭"的记录完整性）；全新环境首次 seed 自动建档。
- **测试可重复**：action_check 第 4 节结束后显式用 `action_cases_from_static()` 的 o1 基线 upsert 复位（门禁自持，不影响运行时语义）。
- **F5**：脚本不进 run_all（真实 key/网络属环境相关），默认无 key → skip（exit 0）。
- **F7**：20s setInterval，仅真实模式（demo 分支不轮询静态）；选择档案时重置定时器，避免陈旧闭包。
- **F9 范围**：只核对"引擎输出 ↔ 后端汇总端点 ↔ 页面同源计数/证据覆盖"；图表静态单列 F11（需引擎驱动图表=新功能）。

## Risks / Trade-offs

- 保留 seed 档案进度意味着"载入样例"不再把演示档案归零 → 用户可用"删除档案"获得干净演示；语义在 UI 文案不突出（低影响）。
- 轮询间隔 20s 最小负担；多端实时由阶段 2 解决。
