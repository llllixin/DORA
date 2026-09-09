## Context

动机与范围见 proposal.md。技术现状（决定本设计的事实）：

- 每个 Repository 写操作使用短会话 `_session_ctx()` 单事务；`flow.verify(resolved)` 先 `repo.verify_action_case`（commit）再 `repo.add_knowledge`（commit）= 两次事务（A2 根因）。
- `delete_action_case` 目前同事务只清 `action_step`；`delete_all_action_cases` 只清 step+case；`case_lesson`/`knowledge_archive` 无级联（A1 根因）。
- 列上限：`ActionCase.archive VARCHAR(500)`；`CaseLesson.archive/resolution` 与 `KnowledgeArchive.content/note` 为 VARCHAR(2000)（A3 根因）。
- `tests/action_check.py` 无孤儿不变式；`tests/run_all.py` STEPS 硬编码 `"python3"`（B1）。
- 当前演示库脏行（apply 前实测）：case o2=running 但 knowledge=opportunity/lesson 两行、case_lesson=o2/p2 两行残留。

## Goals / Non-Goals

**Goals:**
- `knowledge_archive`/`case_lesson` 与 `action_case` 生命周期一致：删除级联、resolved 单事务原子、非 resolved 无孤儿（含门禁自愈）。
- 长处理过程（多轮 continue/长 note）不再越界，TEXT 迁移幂等可重跑。
- run_all 不再依赖外部 `python3` 解释器。
- 当前演示库 o2（及同类 p2）脏行清理，UI 不再显示"running 档案的已归档/经验"。

**Non-Goals:**
- 不改前端/API 契约；不做真实历史"知识保留独立于档案"的归档策略（删除即删，见 Open Questions）。
- 不动 business-watch/engine 语义；不引入迁移框架（alembic 等）。

## Decisions

### D1 级联删除在 Repository 既有事务内显式执行（不靠 DB 外键级联）
`delete_action_case` / `delete_all_action_cases` 在同一个 `_session_ctx()` 事务内，先删 `action_step`，再删 `case_lesson`、`knowledge_archive`（where source_id=case_id），最后删 `action_case`；返回语义不变（单删 True/False，全清 None）。
- 为什么：保留"Repository 显式语义 + 幂等测试可读"；knowledge 行以 `source_id`（非 FK）关联多 entry_type，DB 外键方案无法一步覆盖 case_lesson 与三种类型，且引入 migration 复杂度。
- 备选：`ondelete=CASCADE` 外键 → 需改表结构 + 历史行迁移 + 与 source_id 非唯一关联冲突，否决。

### D2 resolved + 知识入库收敛为单方法单事务
改造 `Repository.verify_action_case(case_id, outcome, note)`：`outcome=resolved` 时在**同一 session**内完成 `status=resolved`、`archive += 验证记录`、插入 knowledge 行（entry_type=row.kind、source_id=case_id、code/title 取自 row、content=archive、note=note），再 commit；`outcome=continue` 保持原行为。`flow.verify` 删除其后的 `repo.add_knowledge` 调用。
- 为什么：单事务消除"已 resolved 但知识缺失"窗口；幂等由 (entry_type, source_id) 唯一约束兜底，重复 create_case_lesson 不新增。
- 兼容：section1 直接调用 `verify_action_case("o-test","resolved")`（无 note）也会写一条知识行——测试随后删除 o-test 走级联清理，不留脏。
- 备选：保留两次调用 + 补偿/重试 → 复杂度高且窗口仍在，否决。

### D3 扩列 TEXT + init_db 幂等 ALTER（仅 PG 方言）
`models` 相应列改 `Text`；`db.init_db()` 在 `create_all` 后对 postgresql 方言执行幂等 `ALTER TABLE ... ALTER COLUMN ... TYPE TEXT` 列表（重复执行为 no-op）。
- 为什么：项目无迁移框架；create_all 不改变已有列类型，必须在 init 时补 DDL；方言守卫避免未来 sqlite/mock 环境语法错误。
- 备选：alembic 引入 → 超范围（Non-Goals）。

### D4 run_all 用 sys.executable
STEPS 中 `["python3", ...]` 全部改 `[sys.executable, ...]`；docstring/注释写明"使用启动 run_all 的解释器运行各 check"。
- 为什么：`python3` 可能指向无依赖的解释器（本机 homebrew vs 服务所在 miniforge，实测全红，P012/B1）。

### D5 孤儿清理 + 门禁自愈
一次性清理采用既有 Repository 方法：`delete_case_lesson("o2"/"p2")` + `delete_knowledge_by_source("lesson","o2")` + `delete_knowledge_by_source("opportunity","o2")`（**不删 action_case**，其仍 running）。action_check 在 main 开头加"自愈"步骤：对每个存在 lesson/knowledge 但 `status != resolved` 的档案执行上述清理，保证脏库不阻断门禁；结尾断言孤儿数为 0。
- 为什么：测试/演示基线复位（F4 upsert_seed_case）是脏行历史来源；门禁自愈让任何环境都能自保持一致。
- 假设（需 review 确认）：`p2` 的 case_lesson 与 o2 同属孤儿（case running），一并清理——超出用户点名"o2 两行"，若保留 p2 经验请否决并仅清 o2。

## Risks / Trade-offs

- [删除 resolved 档案会同时删除其知识/经验归档] → A1 明确语义"档案删除即整条历史删除"；如要"档案删除但知识保留"需另立归档策略（Open Questions）。
- [ALTER 在非 PG/异常环境失败] → 方言守卫 + try/except 记录忽略；PG 主环境反复执行 no-op 验证。
- [级联清理影响现有测试清理顺序] → action_check 各临时案仍有显式删除（幂等），级联后不留孤儿；新增不变式节断言兜底。
- [一次清理删除了 p2 演示经验，UI 抽屉"学习经验"数下降] → 诚实不变式优先；如需演示经验可造 resolved 案（seed 不造假经验，D033）。

## Migration Plan

1. 代码：models Text → db.init_db ALTER（幂等）→ repository 级联/单事务 → flow.verify 单调用 → run_all sys.executable。
2. 数据：跑一遍孤儿清理（o2/p2 case_lesson + o2 knowledge 两行），`action_check` 不变式确认。
3. 回滚：`git revert`（模型/DDL 不改旧行为之外）；已扩 TEXT 列回滚无需收缩（VARCHAR 语义更宽，向后兼容）。

## Open Questions

1. **删除档案后其知识/经验是否应永久保留？** 本 change 按 A1 建议"级联删除（删除即整条历史消失）"。若希望"档案删除但知识归档留作历史"，需要独立的归档保留策略（超出本 change，需另立）。**默认按级联删除评审。**
2. **p2 经验是否一并清理？** 不变式下 p2（running）case_lesson 同属孤儿；本 change 一并清理（D5 假设）。若希望保留 p2 演示经验请在此否决。
