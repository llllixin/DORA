## 1. 模型与 Repository

- [x] 1.1 `models.py` 增 `ActionCase`（id pk=insight_id、kind/tag/tag_cls/case_title/code/source/status、orchestration JSON、archive、时间戳）与 `ActionStep`（自增 id、case_id index、seq、title/desc/evidence/why、status、note/result、finished_at）；验证：`db.init_db()` 建表
- [x] 1.2 `repository.py`：ACTION 状态常量 + CRUD（create/upsert_seed/list/get 含 steps/set_action_step_status done 记时间/verify resolved|continue/delete 级联幂等/delete_all）+ `count_rows` 两项映射；验证：见 1.4
- [x] 1.3 `seed.py`：把 `app.data.ACTIONS` 5 例拍平迁移（前 2 done / current in_progress / 后 2 pending，保留 why 与 code/archive/编排），幂等；验证：重复 seed 行数稳定（见 action_check）

## 2. 测试与收尾

- [x] 2.1 新增 `tests/action_check.py` 第 1 节「领域 CRUD」：seed 幂等（case=5、每案 steps=5 且状态分布正确）→ 单查含 steps → seq3 done(note/result) 往返 → verify resolved → 删除级联 → 幂等删除；`python3 -m tests.action_check` ALL GREEN
- [x] 2.2 `tests/run_all.py` 增 action_check → **7 段**；验证：`python3 -m tests.run_all` 7 段 ALL GREEN（golden 9 不变）
- [x] 2.3 dev-log「迭代 28」+ 路线图 §3C V5-T1 标记 + archive（【测试证据】+【反思】）

【测试证据】action_check → "action_check OK（第 1 节 领域 CRUD + seed 迁移幂等）"（重复 seed：case=5、每案 5 步 done/done/in_progress+pending×2、code 保留 PRF-0831 等；步骤 done 带 note/result/finished_at 往返；verify resolved；删除级联+幂等）；run_all → ALL GREEN（**7 段**，golden 9 不变）。
【反思】静态 ACTIONS 是 camelCase 字段（tagCls/caseTitle），seed 映射时用 snake 一时踩 KeyError——复制迁移优先读源字典实际键；拍平规则（前 2 done/current in_progress/后 2 pending）保留原 ActionPage 视觉语义；run_all 自 T1 达 7 段与 §3C T5 目标一致（同 watch_check 模式）；case id=insight_id 为后续幂等建档打底（D031-2）。
