# v5-action-api

## 1. 服务层与微调

- [x] 1.1 `repository.py`：`verify_action_case(case_id, outcome, note="")`（note 追加 archive，可选默认兼容旧调用）；新增 `set_action_case_status(case_id, status)`；验证：既有 action_check 第 1 节仍绿
- [x] 1.2 `app/action/flow.py`：start/done/block/verify + case 状态同步 + 冻结检查（resolved 拒绝一切推进）；非法迁移抛 ValueError；验证：见 1.4

## 2. REST

- [x] 2.1 `schemas.py` 增 ActionCreateRequest/StepBodyRequest/VerifyRequest；`routers.py` 增 `/api/action/cases`（POST create=builder、GET list、GET /{id}）、`/{id}/steps/{seq}/start|done|blocked`、`/{id}/verify`（ValueError→400、缺 case/step→404）；旧 `/actions*` 不动；验证：curl 冒烟（建档→推进→resolved / 非法迁移 4xx）

## 3. 测试与收尾

- [x] 3.1 `tests/action_check.py` 第 3 节「状态机服务」：flow 建临时档案完整推进（start→done 全 done→waiting_verify→resolved 带 note 入 archive）；blocked→start 恢复；resolved 后 start/done/verify 拒绝；`python3 -m tests.action_check` ALL GREEN
- [x] 3.2 回归：`python3 -m tests.run_all` **7 段 ALL GREEN**（golden 9 不变；e2e Case1/2 execute 契约不变）
- [x] 3.3 dev-log「迭代 30」+ 路线图 §3C V5-T3 标记 + archive（【测试证据】+【反思】）

【测试证据】action_check（第 1–3 节）→ "action_check OK（…状态机服务 全绿）"：pending 直 done 拒绝、start→done 推进、blocked→start 恢复、全 done→waiting_verify、resolved 需 note 且入 archive、resolved 后一切迁移拒绝、continue→running。run_all → ALL GREEN（7 段, golden 9 不变）。API 冒烟（重启后绕代理）：未跌破时建 e2 → 400「不在引擎判定集」；跌破上传后建档 200 created；done on pending → 400；推进至 waiting_verify → verify resolved → 再 verify 400；GET list 6（含 e2 resolved）。

【反思】状态机合法性唯一真源在 flow.py 服务层（repo 只管合法枚举值）；verify note 追加 archive 避免新增列（create_all 无法给已有表加列）；resolved 冻结一切推进由 _get guard 统一拦；旧 /actions 静态保留避免中断 e2e Case1/2，T5 前端切新端点后再下线。
