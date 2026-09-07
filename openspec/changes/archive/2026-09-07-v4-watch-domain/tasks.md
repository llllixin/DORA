## 1. 模型与 Repository CRUD

- [x] 1.1 `models.py` 增 `WatchTarget`（id pk `String(20)`、raw_text `String(500)`、intent `JSON`、status `String(16)`、frequency `String(16)`、last_checked_at/last_event_at/created_at `String(32)`）与 `WatchEvent`（自增 id、target_id `String(20)` index、triggered_at `String(32)`、kind `String(16)`、summary `Text`、values `JSON`），验证：`db.init_db()` 后 PG 出现 `watch_target`/`watch_event` 两表
- [x] 1.2 `repository.py` 增 CRUD：`create_watch_target(text, intent, status="watching", frequency="on_update")`（校验 status/frequency 枚举，`w-`+uuid 生成 id）→ 返回 dict；`list_watch_targets()`；`get_watch_target(id)`；`set_watch_status(id, status)`；`delete_watch_target(id)`（级联清事件、幂等）；`delete_all_watch_targets()`；`add_watch_event(target_id, kind, summary, values)`（kind 校验）；`list_watch_events(target_id)`；`count_rows` 表映射补两项。全部走 `_wrap` + 短会话，验证：直接调 Repository 往返通过（见 1.3）
- [x] 1.3 新增 `tests/watch_check.py` 第 1 节「领域 CRUD」：建→列→查→pause→事件追加×2→列表顺序→删除→查 None→重复删除幂等；`python3 -m tests.watch_check` ALL GREEN
- [x] 1.4 `tests/run_all.py` STEPS 增 `watch_check` 段（6 段）；验证：`python3 -m tests.run_all` **6 段 ALL GREEN**（engine/ingest/reasoning/golden/e2e/watch 全过，golden 9 insights 不变）

## 2. 收尾

- [x] 2.1 dev-log「迭代 22」追加流水（V4-T1 watch 领域与持久化，含测试证据）；路线图 §3B V4-T1 标记完成
- [x] 2.2 归档信息含【测试证据】（watch_check + run_all 6 段输出节选）与【反思】（本次建表/CRUD 模式是否可复用、有无新坑）

【测试证据】`python3 -m tests.watch_check` → "watch_check OK（第 1 节 领域 CRUD 全绿）"；`python3 -m tests.run_all` → **ALL GREEN（6 段）**（engine/ingest/reasoning/golden 9/e2e/watch 全过）。
【反思】Repository 短会话 + `_wrap` 模式对纯增表可零成本复用（枚举校验前置、`w-`+uuid 前缀避免与引擎 id 撞名）；ORM 无 relationship 的级联删除需在同事务显式执行（已做）；CRUD 契约先于 API 落 watch_check 固化防 T3/T4 返工；出厂重置是否清委托留 T3 接线定（倾向保留目标清事件）——届时补 D 记录。
