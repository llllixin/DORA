## Why

2026-09-08 代码审查遗留 Phase 0（持续优化路线 §5/§6）收口。审查发现三类一致性问题，演示库已可见 **o2 矛盾实例**（action_case o2=pending/running，但 `knowledge_archive` 仍残留 opportunity o2 与 lesson o2 两行、`case_lesson` 残留 o2/p2）：

- **A1** `knowledge_archive` / `case_lesson` 不随 `action_case` 生命周期联动——删除档案或测试/演示基线复位会残留孤儿行，且无不变式把关；
- **A2** `flow.verify(resolved)` 与知识自动入库是**两次 commit**（先 `verify_action_case` 再 `add_knowledge`），异常窗口会丢行且无补偿；
- **A3** `ActionCase.archive VARCHAR(500)` 与每次 verify 追加冲突——多轮 continue / 长 note 会触发 PG 越界报错（连带 `case_lesson.archive` 与 `knowledge_archive.content` 同样有 2000 上限）。
- **B1** `tests/run_all.py` 子进程 STEPS 硬编码 `"python3"`，解释器环境不同即全红。

## What Changes

- **A1 生命周期一致（删除级联）**：`Repository.delete_action_case` 与 `delete_all_action_cases` 改为**同一事务**级联清理 `case_lesson` 与 `knowledge_archive`（source_id=case_id、entry_type∈problem|opportunity|lesson），幂等；action_check 新增「生命周期不变式」节：任何非 resolved/不存在档案不得残留 lesson/knowledge 行（含运行前自愈清理，防脏库复发）。
- **A2 resolved 单事务原子**：把"置 resolved + archive 追加 note + 知识自动入库"收敛进同一 Repository 写操作（单 session 单 commit），`flow.verify` 不再二次调用 `add_knowledge`；知识写入保持 (entry_type, source_id) 幂等。
- **A3 扩列 + 幂等迁移**：`action_case.archive`、`case_lesson.archive/resolution`、`knowledge_archive.content/note` 由 VARCHAR 扩为 TEXT；`db.init_db()` 增加**幂等** `ALTER TABLE ... TYPE TEXT`（仅 postgresql 方言，重复执行 no-op），多轮 continue/长 note 不再越界。
- **B1 解释器**：`tests/run_all.py` STEPS 的 `"python3"` 改为 `sys.executable`，docstring/注释说明依赖解释器（AGENT 同步）。
- **数据清理**：对当前演示库执行一次性孤儿清理（o2/p2 的 case_lesson 行、o2 的 knowledge 两行），随后 action_check 不变式全绿。
- **spec**：business-action 增加一条生命周期一致性 Requirement（delta，不可 skip_specs）。

**迁移/兼容说明**：删除档案的语义收紧为"级联删除其经验与知识归档行"（原只删 case+steps）——属 A1 既定收口，非破坏性；前端无改动（知识/经验 UI 读同一查询）。长 archive 由 VARCHAR→TEXT，对现有数据无重写；新增列 DDL 幂等。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `business-action`: 新增需求「归档知识随档案生命周期一致」——resolved 入库与验证同事务原子、档案删除级联清理经验/知识行、非 resolved 不得残留孤儿（含不变式场景）。

## Impact

- 后端：`app/models.py`、`app/db.py`、`app/repository.py`（级联 + 单事务 + 删除方法）、`app/action/flow.py`（verify 原子）、`tests/action_check.py`（不变式节 + 自愈清理）、`tests/run_all.py`（sys.executable）。
- 数据：一次性清理演示库 o2/p2 孤儿行（不删 case）。
- DB：TEXT 迁移幂等 ALTER（仅 PG）。
- 前端：无改动。
- 验证：python 断言脚本（级联/原子/长 note 不越界/孤儿清零）+ `action_check` + `run_all` ALL GREEN（含 interpreter 一致性）。
