## 1. F4 seed 语义

- [x] 1.1 `seed.py seed_action_cases`：档案不存在才 `create_action_case`（不再 upsert 覆盖）；验证：重复 run_seed 不重复、已有进度不被覆盖（action_check）
- [x] 1.2 `tests/action_check.py`：新增"seed 进度保留"断言（推进 p1? 用临时断言 seed 档案 modify? 直接验证存在）+ 第 4 节结束显式复归 o1 基线；重复运行可重现；`python3 -m tests.action_check` ALL GREEN

## 2. F5/F7/F9

- [x] 2.1 新增 `tests/llm_real_smoke.py`（无 key skip；有 key 单条+全量 9/9 断言）；手动跑一次记录输出
- [x] 2.2 WatchPage/ActionPage 20s 轻量轮询（真实模式）；`npm run build`
- [x] 2.3 F9 核对（已执行摸底：9 insights evidence 全覆盖、Pulse counts=列表 counts）；产出结论 + F11 登记

## 3. 收尾

- [x] 3.1 回归：`python3 -m tests.run_all` **7 段 ALL GREEN（重复两次以验证可重现）**；golden 9 不变
- [x] 3.2 docs：优化方向.md F4/F5/F6/F7/F9 状态 + F11 新增；D032；dev-log 迭代 35 + archive（【测试证据】+【反思】）

【测试证据】action_check（第 1–4 节）连跑两次 ALL GREEN（F4 进度保留断言 + o1/o2 基线自复位，可重复）；run_all 连跑两次均 ALL GREEN（7 段, golden 9 不变）；npm run build ✅；llm_real_smoke（真实 DeepSeek）：单条 1.8s + 全量 9/9 updated / 0 fallback（5.3s），数值锁通过 ✅。
【反思】F4 语义=“出厂重置恢复数据、不归零用户已推进的行动档案”（create-only seed 建档）；测试自复位保证门禁可重复而非依赖 sample 重置；F7 先以 20s 轮询缓解跨端不可见，正式推送留阶段 2；F9 摸底证明 9 洞察 evidence 全覆盖 + Pulse counts=列表 counts，新发现的“图表静态”单列 F11 候选。

