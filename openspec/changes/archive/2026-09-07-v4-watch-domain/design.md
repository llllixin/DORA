## Context

见 proposal.md。V4-T1 建地基：目前 Repository 覆盖 engine/upload/reasoning 五张表，模式固定（SQLAlchemy model + 短会话 `_wrap` + dict 契约）。沿用该模式即可，无需新依赖。

## Goals / Non-Goals

**Goals:** watch_target/watch_event 两表模型 + Repository CRUD 原语 + count_rows 映射 + `tests/watch_check.py`（领域 CRUD 段）并入 run_all 6 段；DB 离线行为与现有读接口一致（抛 DataSourceUnavailableError，供上层 503）。

**Non-Goals:** 委托语句解析（V4-T2）；评估器/触发时机（V4-T3）；/api/watch 路由与前端（V4-T4）；升级路径 E2E（V4-T5，watch_check 第 2 节）；任何引擎/上传/推理行为改动。

## Decisions

- **id 风格**：watch target 用字符串主键 `w-` + uuid4 hex 前 12（与洞察 id 不同的确定性前缀，避免与引擎 id 撞名）；watch_event 用自增整型（只被 target 归属，不需要业务可见 id）。
- **字段命名与 schema（T3 接口对齐）**：intent JSON 结构 = `{metric_key, dimension, condition:{type,days,ref}, frequency}`；status 枚举 `watching|paused`；frequency 枚举 `on_update|daily 09:00|weekly` —— Repository 创建/改状态时校验枚举，非法值抛 ValueError（契约早暴露）。
- **时间戳**：与现有模型风格一致用 ISO 字符串（created_at/generated_at 惯例），`datetime.now(timezone.utc).isoformat(timespec="seconds")`。
- **删除级联**：ORM 不加 relationship/cascade（现有模型均无关系），delete_watch_target 内先删事件再删目标，同会话同事务；重复删除幂等（目标已不存在 → no-op）。
- **出厂重置语义（留待 T3 接线时定）**：T1 只提供 `delete_all_watch_targets()` 原语；"sample 重置是否清委托"在 T3 把评估器/重置接线时一并决定（倾向：保留目标、清事件与数据，避免委托语义被样例重置抹掉——届时在 D 系列补记）。
- **run_all 段命名**：T1 即建 `tests/watch_check.py`（第 1 节=领域 CRUD），T5 在同一模块追加第 2 节=升级路径 E2E；run_all 从 T1 起为 6 段，最终也是 6 段（内容递增，不再改编排）。

## Risks / Trade-offs

- 新增表不建迁移工具 → 依赖 `db.init_db` 的 `create_all`（与现状一致）；已存在旧库时 `create_all` 只会补新表，安全。
- CRUD 契约超前于 API（T3/T4 才用）→ 用 watch_check 固化为契约锚点，避免 T3 返工。
- 事件数无上限 → T1 不做分页（当前量级小），T5 前若事件量大再评估裁剪。
