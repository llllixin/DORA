# business-engine Specification

## Purpose
Dora 确定性业务引擎的对外行为契约：输入原始经营数据，产出 Pulse 摘要与 problem/opportunity/change 三类洞察，并伴随可追溯证据与"原因链+下一步"语义。本变更补齐"数据更新事件"与"高客单门店集群机会"两类情形的引擎覆盖，使其不再依赖静态兜底。

## Requirements

### Requirement: 数据更新事件生成 change 洞察
当数据集完成一次更新（含更新时间、新增记录数与受影响指标清单）时，系统 SHALL 生成一条 type=change、id=`c2` 的洞察，标记为"数据更新事件"，且该洞察的 metric/delta 取自更新元数据（如 `+327 条`、`09:32 更新`）。

#### Scenario: 数据集更新后返回数据事件洞察
- **WHEN** 调用 `GET /api/insights?type=change` 且最近一次更新元数据存在
- **THEN** 返回列表包含 id=`c2` 的洞察，其 type 为 change、metric 与 delta 与更新元数据一致

#### Scenario: 数据事件洞察可追溯
- **WHEN** 调用 `GET /api/evidence/c2`
- **THEN** 返回由引擎生成的证据链，包含更新写入的原始行（时间/动作/对象/数值），而非静态占位数据

### Requirement: 高客单门店集群生成机会洞察
当高客单 Top 门店呈现区域性聚集且存在可归纳的商品/动作共性信号时，系统 SHALL 生成一条 type=opportunity、id=`o2` 的洞察，标题/描述/数值（区域占比、代表性指标）来自门店集群源数据。

#### Scenario: 区域性高客单聚集时返回机会洞察
- **WHEN** 门店集群数据显示 Top 高客单门店集中于某区域且占比超过机会阈值
- **THEN** `GET /api/insights?type=opportunity` 返回包含 id=`o2` 的洞察，其区域占比与代表值来自源数据

#### Scenario: 集群机会洞察带语义与证据
- **WHEN** 读取 o2 的 `semantics` 或 `GET /api/evidence/o2`
- **THEN** semantics 提供"主要贡献/进一步定位/下一步"字段，evidence 提供基于门店集群源数据的原始行

### Requirement: 引擎覆盖不依赖静态兜底
凡引擎已覆盖的洞察（含 c2、o2），其列表、详情与证据响应 SHALL 由引擎计算产出；历史静态快照仅保留为其他数据域（如 Watch 展示行）的数据来源，不得再作为这些洞察的响应来源。

#### Scenario: 已覆盖洞察不落入静态兜底
- **WHEN** 请求 `/api/insights/{c2|o2}` 或 `/api/evidence/{c2|o2}`
- **THEN** 响应字段来自引擎计算（含 trigger/factors/semantics），且引擎自检断言 c2、o2 均存在于对应 type 列表
