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

### Requirement: 引擎从持久化数据源计算
引擎的数据来源 SHALL 从进程内常量切换为持久化数据源（Repository，默认 PostgreSQL）：`metric_series`、门店集群与更新事件数据均由 Repository 提供；持久化数据变化后，重新计算 SHALL 反映最新持久化状态。在给定与现有演示数据集相同的数据时，引擎输出 SHALL 与当前引擎自检基线一致。

#### Scenario: 种子数据入库后引擎结果不变
- **WHEN** 演示数据集已种子写入数据库且执行引擎自检
- **THEN** 自检断言（pulse 3/2/4/4、c1/c2/o2 等）全部通过，结果与内存常量版一致

#### Scenario: 数据库不可用时引擎端点报错
- **WHEN** 数据库离线而请求 `/api/pulse` 或 `/api/insights`
- **THEN** 返回明确错误（503），不得回退 Mock 数据

### Requirement: 规则参数可配置
引擎判定所用阈值/目标/条件参数（如利润率目标 18.5、退货基线 3.2、华东升级阈值 -3.0、集群机会占比阈值 60）SHALL 从规则配置存储读取；修改配置后重新计算 SHALL 使用新参数。参数缺失时 SHALL 回退内置默认值。

#### Scenario: 修改阈值后触发条件变化
- **WHEN** 将华东订单升级阈值由 -3.0 改为 -1.5 并触发重算，且当前华东订单跌幅介于两者之间
- **THEN** 对应变化洞察（c1）的触发文案由"保持观察"切换为"已跌破升级阈值"（或等价的可观察结果变化）

#### Scenario: 未配置参数回退默认
- **WHEN** 规则配置存储缺少某参数 key
- **THEN** 引擎使用内置默认值完成计算且不报错

### Requirement: 新品销量洞察的证据对齐
「新品销量快速增长」洞察（id=`c3`）的证据链 SHALL 展示与洞察主题一致的**新品销量原始行**（周标签 + 销量 + 增量），不得再使用其它指标（如利润率）的占位行。

#### Scenario: c3 证据链为新品销量数据
- **WHEN** 请求 `GET /api/evidence/c3`
- **THEN** 返回的 rawRows 首行包含「新品销量」且数据来自新品周销量源数据

#### Scenario: 自检防回归
- **WHEN** 运行引擎自检 `python3 -m tests.engine_check`
- **THEN** 断言 c3 的 evidence kind 为 `new_sku`（非 `margin`）且证据行含新品销量数据

### Requirement: 数据更新后引擎端点即时反映
当数据集通过上传/样例接口完成写入后，引擎端点（`/api/pulse`、`/api/insights*`、`/api/evidence/*`）SHALL 在不重启服务的情况下按请求读取最新 Repository 数据并反映变化。

#### Scenario: 上传新数据改变脉搏结果
- **WHEN** 上传一组与当前种子数值不同的合法数据后调用 `/api/pulse` 或 `/api/insights`
- **THEN** 结果中的相关指标/触发条件体现新数据（与上传前不同）

### Requirement: 跌破阈值自动升级为问题
当华东订单量跌幅跌破配置阈值（默认 -3.0%）时，系统 SHALL 自动生成 type=problem 的洞察 `e2`（如"华东订单量跌破升级阈值"），并将其 metric/delta/semantics 指向对应数据；不再把该情形作为"待升级 change"输出。

#### Scenario: 跌破阈值生成 e2 问题
- **WHEN** 华东订单序列跌幅 ≤ 阈值（如上传跌破 -3% 的数据）
- **THEN** `/api/insights?type=problem` 包含 id=`e2`，且 `/api/insights?type=change` 不再包含对应 c1 变化

#### Scenario: 未跌破仍为变化观察
- **WHEN** 华东订单跌幅介于 -1% 与阈值之间
- **THEN** 保持 change（c1）输出，不生成 e2
