# Dora · V4 Release Notes（Watch 真实委托）

> 发布日期：2026-09-07 ｜ 验收：✅ sign-off（docs/V4_ACCEPTANCE_CHECKLIST.md）
> 一句话：**把"持续关注"从静态列表升级为真实业务委托闭环**——一句话托管 → 解析 → 按频率评估 → 命中事件回业务脉搏，升级只引用引擎判定；由确定性引擎的 east 升级特例泛化为通用 watch 规则骨架。

## 1. V4 交付（迭代 22–26，全部 OpenSpec 归档）
| 任务 | 交付 |
|---|---|
| T1 领域与持久化 | `watch_target`/`watch_event` 表 + Repository CRUD（枚举校验、级联删除、幂等） |
| T2 委托解析 | `app/watch/parser.py` 词典解析（8 指标 key × 别名 × 条件/频率句式）；unknown 显式拒绝 |
| T3 通用评估器+调度 | 条件求值（复用引擎同源序列）+ escalate 白名单（引用引擎 insight）；数据更新即时触发 + 每日/每周进程内 tick |
| T4 UI + REST | watch CRUD/check REST；WatchPage parse 回显→创建→暂停/恢复/删除/检查；Pulse 计数真实化 |
| T5 验收收尾 | Case 3/4 委托升级 E2E（HTTP）入 watch_check 第 4 节；V4 验收清单 + sign-off |

## 2. 核心语义
```text
一句话委托 → parse(intent) → watch_target(DB)
  → 评估（数据更新即时 / daily 09:00 / weekly 进程内线程）
  → 命中 → watch_event(change)
  → 引擎已判定 problem/opportunity（ESCALATION 白名单）→ escalate（引用 engine_insight，不伪造身份）
  → 变化/升级事件回 Pulse「持续关注」（真实计数与状态 Tag）
红线：Watch 不产生 problem/opportunity 身份；unsupported 指标显式拒绝；出厂重置保留委托清事件。
```

## 3. 接口
`POST /api/watch/parse`、`POST /api/watch`、`GET /api/watch[/{id}]`、`PATCH/DELETE /api/watch/{id}`、`POST /api/watch/{id}/check`。

## 4. 质量与验收
- run_all **6 段** ALL GREEN（watch_check 4 节：CRUD/解析/评估器/升级 E2E）✅；golden 9 不变
- 边界：幂等去重、暂停免评、escalate 仅引用引擎 e2、Case 3/4 HTTP E2E、DB 离线 503
- 人工验收 C 段 ✅ + sign-off（2026-09-07）→ V4 标完成

## 5. 下一步
- **V5（Action 真闭环）** 规划已定（路线图 §3C，T1–T5）：洞察→建档→步骤执行→验证→解决/继续→归档（记录驱动，真实外部动作留工具层）。
- 或先做 LLM 兜底阶段 2（异步 job/SSE）；阶段 1 已落地（迭代 27）。
