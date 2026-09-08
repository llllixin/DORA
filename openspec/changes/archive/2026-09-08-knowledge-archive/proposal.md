# knowledge-archive

## Why

用户需求：把"归档内容"按类型放进"数据库"，并让 Dora 能力里有可视的"数据库/知识库"入口。本 change 新增统一 `knowledge_archive` 知识表：resolved 行动档案按其类型（problem/opportunity）自动归档（处理过程全文），「沉淀经验」同时按类型 lesson 入库；前端新增「知识库」页按类型筛选查看。

## What Changes

- 模型：`KnowledgeArchive`（entry_type ∈ problem|opportunity|change|lesson、source_id、code/title/content(处理过程)/note(结论)、created_at、唯一 (entry_type, source_id)）。
- 写入时机：
  - `flow.verify` outcome=resolved → 自动 `knowledge` 行（entry_type=case.kind，content=archive=处理过程）；
  - `repo.create_case_lesson`（沉淀经验）→ 同时写 lesson 行（content=archive，note=resolution）。
- Repository：add_knowledge/list(可按 type)/delete(测试自清)/count_rows。
- REST：`GET /api/knowledge?type=`（返回 entries + stats 各类型计数）；无人工 POST（写入由流程自动）。
- 前端：新增页面 **知识库**（sidebar「◈ 知识库」）：顶部类型筛选 chips（全部/问题/机会/变化/经验，各带计数），下方条目卡片展示 code/title/处理过程 content/结论 note；未归档类型显示空态。

## Capabilities

### Modified Capabilities
- `business-action`: resolved 与经验沉淀自动按类型写入统一知识归档库，可通过知识库接口按类型筛选查看（problem/opportunity/lesson 有数据源，change 预留类型）。

## Impact

- 后端：models/repository/flow/lesson/router/tests(action_check 第 6 节)；前端：types/doraApi/Sidebar/App/KnowledgePage(新)。
- 验证：action_check 第 6 节；run_all 7 段 ALL GREEN；npm build。
