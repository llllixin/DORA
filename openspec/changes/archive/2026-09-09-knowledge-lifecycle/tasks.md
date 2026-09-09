## 1. A2 · resolved 知识入库单事务原子

- [x] 1.1 改造 `Repository.verify_action_case`：resolved 在同一 session 内完成置态/archive 追加/写 knowledge，再 commit；`flow.verify` 删除二次 `add_knowledge` 调用 → 验证脚本：`[1.1] resolved 单事务原子 OK | knowledge rows = 1`（resolved 返回即知识行存在，archive 含验证 note）
- [x] 1.2 幂等回归：重复 verify 拒绝 / 重复 `create_case_lesson` created=False 且行数不增 → 验证脚本：`[1.2] 幂等 OK | lesson 行数 = 1`；action_check 第 3/5/6 节断言绿

## 2. A1 · 档案删除级联清理

- [x] 2.1 `delete_action_case` / `delete_all_action_cases` 同事务级联删 case_lesson + knowledge（source_id）→ 验证脚本：`[2.1] 删除级联 + 幂等 OK`、`[2.1] delete_all 级联 OK（已 run_seed 还原基线）`（step/lesson/knowledge 三表同清、重复删除 False）
- [x] 2.2 `action_check` 生命周期不变式（main 开头自愈清理 + 结尾孤儿=0 + stdout 计数留痕）→ `[lifecycle] self-heal removed orphan rows: knowledge=3, case_lesson=2`；`action_check OK（第 1–6 节 + 生命周期不变式 … 全绿）`
- [x] 2.3 `upsert_seed_case` 不倒退 resolved 案（补充①）→ 验证脚本：`[2.3] upsert 不倒退 resolved OK`（resolved 案 upsert 后仍 resolved、knowledge 仍在）

## 3. A3 · archive 扩列 TEXT + 幂等迁移

- [x] 3.1 `models.py` 五列改 `Text`（action_case.archive、case_lesson.archive/resolution、knowledge_archive.content/note）→ 全部断言脚本跑通（含 import）
- [x] 3.2 `db.init_db()` 幂等 ALTER（PG 方言，两遍 no-op）→ 验证脚本：`[3.2] TEXT 迁移幂等 OK（init_db 两遍，5 列均 text）`
- [x] 3.3 长处理过程端到端（多轮 continue + 长 resolved note >500）→ 验证脚本：`[3.2/3.3] 长 archive OK | len=686 knowledge_content_len=686`（旧 VARCHAR(500) 会 PG 越界，修复后通过）

## 4. B1 · run_all 解释器一致性

- [x] 4.1 `tests/run_all.py` STEPS 改用 `sys.executable` + docstring 说明 → 验证：`grep -c 'sys.executable' tests/run_all.py` = 8、字面 `"python3"` 计数 = 0；`/Users/tomara/miniforge3/bin/python3 -m tests.run_all` 无需 PATH hack → **run_all: ALL GREEN**

## 5. 演示库孤儿清理 + 全量回归

- [x] 5.1 孤儿清理（o2/p2 的 case_lesson + o2 的 knowledge，不删 action_case）→ 人为造孤儿后 action_check 自愈：`knowledge=3, case_lesson=2` 清空；post-state lessons=0/knowledge=0/5 seed cases 完好
- [x] 5.1b 清理留痕 + 计数入测试证据（补充②）→ 上述 `[lifecycle] self-heal removed orphan rows: knowledge=3, case_lesson=2` 输出留档，计数写入归档【测试证据】
- [x] 5.2 全量门禁回归：`/Users/tomara/miniforge3/bin/python3 -m tests.run_all` → **ALL GREEN**（reasoning/golden 9/e2e 4/watch/action 均绿）；`openspec validate --changes` 通过
