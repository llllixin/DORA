# v4-watch-acceptance

## Why

V4-T1..T4 已落地委托数据层→解析→评估/调度→UI/REST。T5 把文档第 36 章 Case 3/4 的 **Watch 委托**端到端路径固化为门禁（变化→watch 事件；继续恶化→引擎升级 e2→escalate 事件回脉搏），并产出 V4 验收清单（自动门禁 + 边界审查 + 人工核对 + sign-off 位），供 sign-off 后把版本速览 V4 标为完成。

## What Changes

- `tests/watch_check.py` 第 4 节「升级路径 E2E（HTTP）」：
  - 复用 `tests/e2e_api_check` 的 no-proxy helpers 与 east_breach_csv。
  - Case 3：创建 east_orders 委托（POST /watch）→ 即时评估命中 → `GET /watch/{id}` 出现 change 事件（变化回到脉搏）。
  - Case 4：上传跌破阈值 CSV → on_update 触发评估 → 引擎产出 problem e2，同时委托出现 `escalate` 事件（`values.engine_insight=="e2"`）且列表卡片"已升级"。
  - 清理：DELETE 委托 + sample 还原出厂。
- `docs/V4_ACCEPTANCE_CHECKLIST.md`：A 自动门禁（run_all 6 段 + build + watch_check）／B 边界审查（幂等去重、暂停免评、出厂重置清事件留委托、escalate 仅引擎判定、支持范围显式）／C 人工核对（界面委托创建回显、Pulse 计数、升级标签）＋ Sign-off 表。

## Capabilities

- 无 spec 变更（skip_specs）：Case 3/4 的契约已由 v4-watch-evaluator/v4-watch-ui 的 Requirement 与 Scenario 覆盖，本节只把它们固化为可复现门禁。

## Impact

- 后端测试：`tests/watch_check.py`（+第 4 节，需后端在运行——run_all 已有此前置）。
- 文档：`docs/V4_ACCEPTANCE_CHECKLIST.md` 新增；dev-log 迭代 26；路线图 §3B V4-T5 ✅。
- 验证：run_all 6 段 ALL GREEN（watch_check 第 4 节含 HTTP E2E）；golden 9 不变。
