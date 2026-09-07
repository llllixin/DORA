# v5-action-api

## Why

V5-T1/T2 已有档案/建档引擎但没有可操作的执行层。T3 把 Case 变成可推进的状态机：步骤 start/done/blocked（含 note/result 回填）与档案 verify resolved/continue，非法迁移拒绝；对外暴露 `/api/action/cases` REST（建案入口复用 T2 builder）。旧 `/api/actions` 静态端点保留到 T4/T5（前端/e2e 切换后再下线，避免中途破坏 Case1/2 门禁）。

## What Changes

- `app/action/flow.py` 服务层（状态机合法性唯一真源）：
  - `start_step`（仅 pending|blocked→in_progress）、`done_step`（仅 in_progress→done，写 note/result，全 done→waiting_verify）、`block_step`（仅 in_progress→blocked）；
  - `verify(repo, case_id, outcome, note)`：resolved 仅当 waiting_verify（全步骤 done）且 note 追加进 archive；continue→running；已 resolved 档案拒绝再迁移；
  - case 状态自动同步（open 首次推进→running；全 done→waiting_verify）。
- Repository 微调：`verify_action_case` 支持 note 追加进 archive；新增 `set_action_case_status`。
- REST（`/api/action/cases`，新端点；旧 `/actions` 不动）：
  - `POST /api/action/cases {insight_id}` → builder 建档（幂等/拒绝 400）
  - `GET /api/action/cases` / `GET /{case_id}`（含 steps）／`POST /{id}/steps/{seq}/start|done|blocked`／`POST /{id}/verify`
- schemas：ActionCreateRequest/StepBodyRequest/VerifyRequest。
- `tests/action_check.py` 第 3 节「状态机服务」用例。

## Capabilities

### Modified Capabilities
- `business-action`: 档案步骤可执行推进（start/done/blocked 带回填）并自动同步档案状态；验证以 resolved/continue 归档或继续；非法迁移与已归档档案拒绝推进。

## Impact

- 后端：`app/action/flow.py`、`repository.py`（note/状态微调）、`schemas.py`、`routers.py`、`tests/action_check.py`。
- 前端不改（T4 接线）；旧 `/api/actions` 静态端点保留（T5 随 e2e 切换后下线）。
- 验证：action_check 第 3 节全绿；run_all 7 段 ALL GREEN；端点冒烟（建档→start→done→verify resolved / 非法迁移 409）。
