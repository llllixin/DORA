# Dora · V4（Watch 真实委托）验收与审查清单

> 对应：docs/版本路线图.md §3B。V4-T1..T5（迭代 22–26）归档后填写；自动项给出命令，人工项给出核对标准。
> 流程沿用 V3：A 自动门禁 ✅ 可由命令复现 → B 边界审查 → C 人工界面核对（**需你在运行界面确认**）→ D 收尾 → Sign-off。

## 审查状态（2026-09-07）
- **A · 自动门禁 ✅**：`tests/run_all` **6 段 ALL GREEN**（engine/ingest/reasoning/golden/e2e/watch）；`npm run build` ✅；watch REST 冒烟全绿 ✅
- **B · 边界审查 ✅**
  - B1 领域：CRUD 往返/枚举校验/删除级联·幂等/未知 id 不抛错（watch_check 第 1 节）
  - B2 解析：支持句式、跌破+频率词、中文数字、unknown 显式拒绝、建议 chips 5 支持 1 拒绝（第 2 节）
  - B3 评估：命中/未命中/幂等去重/**escalate 仅引用引擎 e2**/周期到期注入 now/出厂重置保留委托清事件（第 3 节）
  - B4 升级 E2E：Case 3 变化→watch 事件 + Case 4 上传跌破 → 引擎 e2 + 委托"已升级"卡片（第 4 节，HTTP）
  - B5 golden 锚点：9 insights 模板基线不变（golden_check）
- **C · 人工核对**：待你在运行界面确认（见下），完成后填 Sign-off。

## A. 自动门禁（归档前全部通过 ✅）
- [x] `cd backend && python3 -m tests.run_all` → **ALL GREEN（6 段）**（engine / ingest / reasoning / golden 9 / e2e 4 case / watch 4 节）
- [x] `cd frontend && npm run build` → 通过（tsc + vite）
- [x] watch REST 冒烟（绕代理）：create→list→pause→check→unsupported 400→delete 全链路

## B. 红线/边界审查（已自动覆盖 ✅）
- [x] **升级不伪造身份**：`ESCALATION` 白名单 + 仅引擎产出对应 insight 才 escalate（watch_check 第 3/4 节断言 `engine_insight=="e2"`）
- [x] **暂停不评估**：status=paused 委托不进 evaluate_all/_is_due
- [x] **支持范围显式**：unknown 指标 parse ok=false + unsupported 400 detail，绝不静默
- [x] **幂等**：重复评估同数据去重不刷屏；删除/重复删除安全
- [x] **出厂重置语义**：sample 重置保留委托、清事件（旧数据引用失效）

## C. 功能人工核对（需在运行界面确认）
- [ ] 打开 http://localhost:5173/watch：输入"帮我关注华东销售额，如果连续三天下降就提醒我" → 让 Dora 理解 → 出现解析回显（业务目标/指标口径/触发条件/频率）→ 开始持续关注 → 列表出现该委托（观察中）
- [ ] 点击「检查」手动评估；「暂停」后状态=已暂停且再上传数据不产生新事件；「恢复」可继续；「删除」移出列表
- [ ] 上传跌破华东 -3% 的 CSV（或等待调度）后：委托 Tag 变「已升级」(红)，Pulse 持续关注计数随之变化
- [ ] Pulse「持续关注」卡片与计数来自真实委托（不再是静态 6 条）；后端离线时才显示本地演示数据

## D. 收尾核对
- [ ] dev-log 迭代 22–26、路线图 §3B V4-T1..T5 与版本状态、README 归档索引（17 个 change）、business-watch spec（4 需求 + 来源表）已同步
- [ ] 大版本切换记录：sign-off 后把路线图版本速览 V4 标为完成（记录迭代 26）

## Sign-off
| 审查人 | 日期 | 结论（通过/待改） | 备注 |
|---|---|---|---|
| | | | |
