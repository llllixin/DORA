## ADDED Requirements

### Requirement: 归档知识随档案生命周期一致（删除级联 + resolved 入库原子 + 无孤儿不变式）

系统 SHALL 保证 `action_case`、`case_lesson`、`knowledge_archive` 三表生命周期一致：

1. 当行动档案被删除（单删或全清）时，同一数据库事务内 SHALL 级联删除其全部 `action_step`、`case_lesson` 与 `knowledge_archive`（source_id=该档案 id）行，不残留孤儿；重复删除幂等返回 False。
2. 行动档案 verify resolved（含 note 追加 archive）与其知识自动入库（按 case.kind 写 problem|opportunity 行）SHALL 在同一数据库事务内完成——不允许出现"档案已 resolved 但知识行缺失"的中间态；知识写入按 (entry_type, source_id) 幂等。
3. 任何 status ≠ resolved 或不存在的档案不得存在其 `case_lesson` / `knowledge_archive` 行（不变式）；测试门禁 SHALL 在运行前自愈清理脏库中的此类孤儿并在结束后断言该不变式成立。

#### Scenario: 删除档案级联清理经验与知识

- **WHEN** 一个已 resolved 且已沉淀经验（存在 case_lesson 与 problem/opportunity + lesson 知识行）的档案被 delete_action_case
- **THEN** 该档案的 action_step、case_lesson 与全部 knowledge_archive 行在同事务内一并消失；再次删除返回 False（幂等）

#### Scenario: resolved 入库原子且幂等

- **WHEN** 对全 done 档案 flow.verify outcome=resolved（带 note），随后重复 verify 被拒绝、再 create_case_lesson 两次
- **THEN** verify 返回时该档案已 resolved 且对应知识行（含处理过程 archive 与 note）在同一事务内已存在；重复 verify 4xx；重复沉淀 lesson created=False 且不新增行

#### Scenario: 非 resolved 档案无孤儿行（不变式）

- **WHEN** 遍历全部 action_case 并核对 case_lesson / knowledge_archive
- **THEN** 不存在 status=running/waiting_verify/open 的档案仍带有 lesson 或 knowledge 行；运行前发现的脏行被自愈清理
