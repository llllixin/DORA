## Why

路线图 C5 = 把文档第 36 章的 4 个核心验收用例固化为可自动跑的 E2E 门禁，并补齐缺失的"Watch→跌破阈值→自动升级 Problem"行为（此前只停在 change 待升级），让"归档前自动 gate"真正成立。

## What Changes

- 引擎行为补齐：华东订单量若跌破升级阈值，自动升级为 problem（新增洞察 `e2`）；未跌破仍按 change（c1）观察。
- 新增自动门禁脚本：
  - `backend/tests/e2e_api_check.py`：针对运行中的后端 API 跑 4 个核心用例（Problem→Evidence→Action / Opportunity→复制验证→Action / Change→Watch / Watch→升级→Problem）。
  - `backend/tests/run_all.py`：一键串联 `engine_check` + `ingest_check` + `e2e_api_check`（子进程），返回非零即失败。
- 门禁纳入约定：change 归档/提交前默认跑 `python3 -m tests.run_all`（后端在线的本地/CI 环境）。
- 文档/看板：路线图 C5 勾选；D/P 记录自动升级与门禁决策。

## Capabilities

### New Capabilities
<!-- 无（工具/门禁脚本属工程护栏，不进产品能力 spec） -->

### Modified Capabilities
- `business-engine`: 「持续关注/变化」的升级语义——华东订单量跌破升级阈值时，系统 SHALL 自动生成 problem（id=`e2`），而不再仅输出带"待升级"标记的 change。

## Impact

- 后端：`app/engine/engine.py`（e2 信号/模板/semantics）、`backend/tests/e2e_api_check.py`、`backend/tests/run_all.py`。
- 文档：`.clinerules/project-conventions.md`（门禁命令）、README 验证节、开发记录迭代、路线图 C5、问题与经验（D019）。
- 非目标：V4 的定时调度/真执行；浏览器级 UI E2E（本轮为 API 级 E2E）。
