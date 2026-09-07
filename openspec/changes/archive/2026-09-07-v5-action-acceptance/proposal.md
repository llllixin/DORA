# v5-action-acceptance

## Why

V5-T1..T4 已完成档案持久化/建档/状态机 API/前端真实化。T5 把文档第 34 章 Action 闭环（Case 4 升级→建档→执行→验证→归档 与 Case 2 机会→验证→continue）固化为 HTTP 门禁（action_check 第 4 节），并产出 V5 验收清单（A/B/C + Sign-off），供 sign-off 后把 V5 标为完成。

## What Changes

- `tests/action_check.py` 第 4 节「闭环 E2E（HTTP）」：
  - Case 4+1 链：sample → 建 watch → 无 e2 档案断言 → 上传跌破 → 引擎 e2 → `POST /action/cases {e2}` created=True → 步骤全 done → verify resolved（note 入 archive）→ list 含 e2 resolved。
  - Case 2：静态 o1 档案推进至 waiting_verify → verify continue → running（可复制验证→继续）。
  - 清理：删除 e2 档案 + sample 还原（action 档案不被 sample 重置，显式清理）。
- `docs/V5_ACCEPTANCE_CHECKLIST.md`：A 自动门禁（run_all 7 段/build/action_check）/B 边界审查记录/C 人工界面核对/D 收尾 + Sign-off 表（C 留用户在界面确认）。

## Capabilities

- 无 spec 变更（skip_specs）：闭环契约已由 v5-action-domain/builder/api/ui 四 change 的 Requirement 覆盖。

## Impact

- 测试：`tests/action_check.py`（+第 4 节，需后端运行，run_all 已有此前置）。
- 文档：`docs/V5_ACCEPTANCE_CHECKLIST.md`；dev-log 迭代 33；路线图 §3C V5-T5 ✅ + 版本速览 V5 → 🔶 已实现待人工验收。
- 验证：run_all 7 段 ALL GREEN；golden 9 不变。
