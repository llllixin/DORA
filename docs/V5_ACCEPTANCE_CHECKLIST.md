# Dora · V5（Action 真闭环）验收与审查清单

> 对应：docs/历史版本路线.md §3C（V5 规划已归档）。V5-T1..T5（迭代 28–33）归档后填写；自动项给命令，人工项给核对标准。

## 审查状态（2026-09-07）
- **A · 自动门禁 ✅**：`tests/run_all` **7 段 ALL GREEN**（engine/ingest/reasoning/golden/e2e/watch/action）；`npm run build` ✅；action_check 4 节全绿 ✅
- **B · 边界审查 ✅**
  - B1 领域：seed 幂等（5 case × 5 steps，code 保留）、CRUD/级联删除/verify resolved（action_check 第 1 节）
  - B2 建档：仅当前引擎判定 problem/opportunity 可建档（change/伪造拒绝）、e2 升级后可建、重复幂等返回既有（第 2 节）
  - B3 状态机：pending 直 done 拒绝、blocked→start 恢复、全 done→waiting_verify、resolved 需 note 入 archive、resolved 冻结、continue→running（第 3 节）
  - B4 闭环 E2E：Case4+1（watch→跌破→e2 建档→执行→resolved 归档）+ Case2（o1→continue）（第 4 节，HTTP）
  - B5 golden 锚点：9 insights 模板基线不变
- **C · 人工核对**：待你在运行界面确认后填 Sign-off

## A. 自动门禁（✅ 已全部通过）
- [x] `cd backend && python3 -m tests.run_all` → **ALL GREEN（7 段）**
- [x] `cd frontend && npm run build` → 通过
- [x] action_check（第 1–4 节：领域/建档/状态机/闭环 E2E）全绿

## B. 红线/边界审查（已自动覆盖 ✅）
- [x] **回写不污染判定**：resolved 只认 verify + note（archive），不改引擎判定/reasonSource
- [x] **仅引擎判定可建档**：watch escalate 不自动建档；change/伪造 400
- [x] **状态机冻结**：resolved 后一切迁移拒绝（400）；非法迁移不写状态
- [x] **seed 幂等**：重复 seed 不翻倍；后端离线前端才走 demo 兜底

## C. 功能人工核对（需在运行界面确认）
- [x] 洞察详情（problem/opportunity）点「加入行动回路」→ 跳到 Action 页出现该档案（已 seed 的返回既有）；对 change 仍是「加入持续关注」
- [x] Action 页：列表来自后端；任选档案 → 步骤「开始/完成/受阻」可点击并回填备注/结果（当前步骤备注框）
- [x] 把所有步骤推进到完成 → 状态=待验证 → 填验证说明点「归档 · 问题解决」→ 显示已归档（含验证记录）；或点「继续观察」→ 状态=执行中
- [x] 打开 e2 类新问题：上传跌破数据后在引擎判定集内 → 加入行动回路可建档成功（400 情况会显示原因而非伪造成功）
- [x] 关掉后端再进 Action 页 → 显示"离线演示"兜底（不报错）

## D. 收尾核对
- [x] dev-log 迭代 28–33、路线图 §3C V5-T1..T5 与版本状态、README 归档索引（25 个 change）、business-action spec（4 需求 + 来源表）已同步
- [x] 大版本切换记录：sign-off 后把路线图版本速览 V5 标为完成

## Sign-off
| 审查人 | 日期 | 结论（通过/待改） | 备注 |
|---|---|---|---|
| tomara（用户确认） | 2026-09-07 | 通过（V5 标为已完成，迭代 28–33） | C 段界面核对已确认（洞察建档入口 / 步骤执行与回填 / 待验证→归档·继续 / 引擎判定建档 / 离线 demo 兜底）；A/B 自动证据见上 |
