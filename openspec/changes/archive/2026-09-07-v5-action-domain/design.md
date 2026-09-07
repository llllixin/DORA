## Context

见 proposal.md。V4 确立了 Repository 短会话模式（watch 同款）。静态 ACTIONS 5 例字段已知（app/data.py）。V5-T1 只做持久化 + seed 迁移；状态机语义在 T2/T3 上 API。

## Goals / Non-Goals

**Goals:** 两表模型 + repo CRUD/状态原语 + 5 例 seed 迁移（幂等）+ action_check 第 1 节 + run_all 7 段。

**Non-Goals:** 建档引擎（T2）；/api 执行验证（T3）；前端（T4）；闭环 E2E（T5）；watch 关联。

## Decisions

- **case id = insight_id**（p1/o1/e2…）：V5 建档按 insight 幂等（D031-2），id 天然唯一且可追溯。
- **静态 5 例拍平**：每 case 存 5 行 step —— steps[0]/steps[1]=done、current(含 why)=in_progress、steps[2]/steps[3]=pending；保留 code/编排/archive 文案，ActionPage 未来渲染与旧静态视觉一致。
- **steps 表带 why/note/result/finished_at**：why 承载"当前行动理由"，note/result 是执行/验证回填位（T3 用），一次性建模避免再迁移。
- **状态常量**：case open|running|waiting_verify|resolved；step pending|in_progress|done|blocked。repo 只做"写入合法值校验 + 记录时间"，**迁移合法性规则留给 T3 服务层**（T1 不发明业务规则）。
- **seed 幂等 = 按 pk upsert + 重建 steps**（同事务删旧插新），重复 run_seed 不翻倍。
- run_all 自 T1 增 action_check → 7 段（§3C T5 的"7 段"以 T1 即达成的形态保持到最后，与 watch_check 同模式）。

## Risks / Trade-offs

- 状态机合法性不在 repo 层 → 测试需自持（T3 API 层再强约束），避免 T1 过度建模。
- steps 拍平行数 5/案 为迁移快照，未来 builder 建档步骤数不同（≥3）无碍（seq 泛型）。
- 新增表由 `db.init_db().create_all` 补建（与既有表一致，无迁移工具）。
