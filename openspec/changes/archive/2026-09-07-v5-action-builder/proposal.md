# v5-action-builder

## Why

V5-T1 有了 action_case/action_step 与静态 5 例种子，但没有"从引擎洞察自动建档"。T2 补建档引擎：把引擎判定的 problem/opportunity 洞察（含 V4 升级触发的 e2 这类新 problem）变成可执行 Case + 步骤，重复触发幂等返回既有档案；change 类与 watch escalate 事件**不建档**（D031-2：只有引擎判定 problem/opportunity 才算行动入口）。

## What Changes

- `app/action/builder.py`：`create_case_from_insight(repo, insight)` →
  - 校验：insight.type ∈ {problem, opportunity} 且 id 存在于当前 `run_engine(repo)` 判定集（拒绝 change / 伪造 id / 升级事件伪冒）；
  - 幂等：`repo.get_action_case(insight.id)` 已有 → 返回既有（created=False）；
  - 建档：case（id=insight.id、kind、tag/tag_cls、title/code/source、status=open、默认编排）+ 4 步模板（发现 done → 定位/拆解 in_progress → 验证 pending → 归档 pending），desc/evidence 引用洞察 trigger/metric/delta/问题；
  - code 确定性生成：`PRB-`/`UPC-` + sha1(insight_id) 前 4 位（种子既有 code 不受影响）。
- `tests/action_check.py` 第 2 节「建档引擎」用例。

## Capabilities

### Modified Capabilities
- `business-action`: 引擎判定的 problem/opportunity 洞察可一键建档为行动档案（步骤模板 + 事实引用，按洞察幂等）；非判定/伪造身份不得建档。

## Impact

- 后端：`app/action/builder.py` 新增、`tests/action_check.py` 第 2 节、`seed.py` 不改（静态 5 例仍走 upsert_seed）。
- 前端/routers 不改（T3/T4 接线）。
- 验证：action_check 第 1+2 节全绿；run_all 7 段 ALL GREEN；golden 9 不变。
