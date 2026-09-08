## ADDED Requirements

### Requirement: 归档与经验按类型写入统一知识库并可筛选
系统 SHALL 提供 `knowledge_archive`：当行动档案 verify resolved 时按类型（problem|opportunity，取自档案 kind）自动写入一条含完整处理过程（archive）的知识；当档案沉淀经验（case_lesson）时按类型 lesson 再写入一条（含处理过程与结论）。同类型同来源幂等（(entry_type, source_id) 唯一）。系统 SHALL 提供知识库查询：可按类型筛选并返回各类型计数；类型 change 为预留（无来源时不产生数据）。

#### Scenario: resolved 与沉淀经验自动按类型入库
- **WHEN** 档案 verify resolved，随后对该档案沉淀经验
- **THEN** knowledge_archive 出现两条：problem（content=处理过程）与 lesson（content=处理过程、note=结论）；重复动作不新增（幂等）

#### Scenario: 按类型筛选与统计
- **WHEN** GET /api/knowledge?type=problem
- **THEN** 只返回 problem 类条目且 stats 反映各类型计数
