# v5-action-domain

## Why

V5 把"加入行动回路"升级为真实 Case 状态机（§3C）。T1 是数据层地基：`action_case`（洞察来源/档案编号/状态机）与 `action_step`（步骤状态/note/result）必须可持久化、可 CRUD、可清空；同时把现有 5 例静态 ACTIONS（PRF-0831/RTN-0816/ORD-1022/UPC-0418/STO-0607）迁为 DB 种子（D031-4），ActionPage 后续改读 DB 时视觉零变化。

## What Changes

- 模型：`ActionCase`（id=insight_id pk、kind、tag、tag_cls、case_title、code、source、status open|running|waiting_verify|resolved、orchestration JSON{experts,data,expertDesc}、archive、created_at/updated_at）与 `ActionStep`（自增 id、case_id、seq、title、desc、evidence、why、status pending|in_progress|done|blocked、note/result、finished_at）。
- Repository CRUD（短会话 + `_wrap`，与 watch 同款）：
  - `create_action_case`（单事务建 case+steps）、`upsert_seed_case`（幂等迁移）、`list_action_cases`、`get_action_case`（含 steps）
  - `set_action_step_status(case_id, seq, status, note?, result?)`（done 自动写 finished_at；状态校验前置）
  - `verify_action_case(case_id, outcome, note)`（resolved→case resolved / continue→running）
  - `delete_action_case`（级联清 steps、幂等）、`delete_all_action_cases`
  - `count_rows` 表映射补两项
- `seed.py`：`run_seed` 内把 `app.data.ACTIONS` 5 例按"steps[0]/steps[1]=done、current=in_progress、steps[2..3]=pending"拍平迁移（保留档案编号/编排/归档文案），幂等。
- `tests/action_check.py` 第 1 节「领域 CRUD」；`run_all` 增 action_check → **7 段**（与 §3C T5 目标一致，模块 T1 起即挂门禁）。

## Capabilities

### New Capabilities
- `business-action`: Action 闭环的持久化契约 —— case/step 两表 + CRUD/状态原语，V5 首个归档 change 建立该能力 spec。

## Impact

- 后端：`models.py`、`repository.py`、`seed.py`、`tests/action_check.py`、`tests/run_all.py`。
- 不改：引擎判定、routers（仍静态吐 ACTIONS，T3/T4 切 DB）、前端、既有 6 段测试行为（golden 9 不受影响）。
- 验证：action_check 第 1 节全绿；run_all **7 段 ALL GREEN**；seed 幂等（重复 run_seed 不翻倍）。
