## Context

见 proposal.md。T1 已有 repo.create_action_case（同 id 已存在抛错）与 seed。T2 在其上加"引擎判定校验 + 模板 + 幂等返回既有"的业务层。

## Goals / Non-Goals

**Goals:** builder 建档（校验/模板/幂等）+ action_check 第 2 节。

**Non-Goals:** REST 入口（T3/T4）；步骤状态机合法性（T3 服务层）；watch escalate → 自动建档（红线禁止）；builders 对静态 5 例重建（seed 路径不变）。

## Decisions

- **判定校验 = 当前 run_engine 快照 + type**：建档时跑一次 `run_engine(repo)`，仅当 insight.id ∈ {problem, opportunity} 结果集才可建——天然拒绝 change/伪造/watch escalate；代价是一次引擎计算（毫秒级，建档低频）。
- **code 确定性**：新档案 `PRB-`(problem)/`UPC-`(opportunity) + sha1(insight_id)[:4].upper()（可复现、不撞号）；静态 seed 的 PRF-0831 等 code 不受影响（不经 builder）。
- **4 步模板**：发现(done, 引 trigger/desc) → 定位·拆解(in_progress, why 引 question) → 验证(pending) → 归档(pending)；与静态 5 步（含前历史 done）语义一致但更贴合"新建即开始"。
- **幂等分层**：builder 先查既有档案（返回 created=False）；否则 `repo.create_action_case`（其同 id 已存在抛 ValueError 兜底，双保险）。
- 默认编排按 kind 模板（问题：经营分析/财务；机会：经营增长/商品），专家可增补（T4 前不改）。

## Risks / Trade-offs

- 新 code 与种子风格不同（PRB-xxxx 与 PRF-0831）→ UI 只作展示，可接受；如要统一序列号需计数表（不引入，代码+id 足够追溯）。
- 每次建档 run_engine 快照 → 若调用瞬间数据已变，洞察可能不在快照而被拒（正确行为：以最新判定为准）。
