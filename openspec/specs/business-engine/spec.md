# business-engine Specification

## Purpose
Dora 确定性业务引擎的对外行为契约：输入原始经营数据，产出 Pulse 摘要与 problem/opportunity/change 三类洞察，并伴随可追溯证据与"原因链+下一步"语义。本变更补齐"数据更新事件"与"高客单门店集群机会"两类情形的引擎覆盖，使其不再依赖静态兜底。

## 需求来源表（Traceability）

| 需求 | 由谁新增 | 归档 change | 迭代 |
|---|---|---|---|
| 数据更新事件生成 change 洞察（c2） | C1 引擎覆盖 | `changes/archive/2026-09-07-extend-engine-coverage` | 9 |
| 高客单门店集群生成机会洞察（o2） | C1 引擎覆盖 | 同上 | 9 |
| 引擎覆盖不依赖静态兜底 | C1 引擎覆盖 | 同上 | 9 |
| 引擎从持久化数据源计算 | C2 PostgreSQL | `changes/archive/2026-09-07-postgres-repository` | 10 |
| 规则参数可配置 | C2 PostgreSQL | 同上 | 10 |
| 新品销量洞察的证据对齐（c3） | c3 证据修复 | `changes/archive/2026-09-07-fix-new-sku-evidence` | 11 |
| 数据更新后引擎端点即时反映 | C3 真实上传 | `changes/archive/2026-09-07-dataset-upload` | 12 |
| 跌破阈值自动升级为问题（e2） | C5 E2E 门禁 | `changes/archive/2026-09-07-e2e-guardrails` | 14 |
| 无指标数据时不产洞察 | V2 边界修复 | `changes/archive/2026-09-07-fix-v2-critical-boundaries` | 16 |
| 阈值比较语义显式化 | V2 边界修复 | 同上 | 16 |
| 时间戳取自更新事件 | V2 边界修复 | 同上 | 16 |
| 洞察语义可来自推理缓存并标注来源 | V3-T2 语义缓存 | `changes/archive/2026-09-07-v3-semantics-cache` | 18 |
| LLM 解释可配置且不污染判定 | V3-T3 LLM | `changes/archive/2026-09-07-v3-llm-provider` | 19 |
| 数据变更后缓存失效 | V3-T3 LLM | 同上 | 19 |
| 洞察刷新在外部推理服务降级时有界有据 | LLM 兜底阶段 1 | `changes/archive/2026-09-07-llm-refresh-policy` | 27 |
| 洞察严重等级由数据结构化计算 | 洞察判断结构化 | `changes/archive/2026-09-11-insight-judgment-structure` | 46 |
| 洞察可能后果由引擎确定性外推 | 洞察判断结构化 | 同上 | 46 |

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

### Requirement: 无指标数据时不产洞察
当 Repository 中不存在任何 `metric_series` 数据时，引擎 SHALL 返回空 Pulse（各计数 0、`last_updated='--'`）且不产出任何洞察——即使更新事件或门店集群表仍残留数据。

#### Scenario: 指标序列清空后引擎静默
- **WHEN** `metric_series` 为空而 `data_update_log`/`store_cluster_store` 仍有数据
- **THEN** `/api/insights` 为空、`/api/pulse` 计数为 0 且 `last_updated='--'`

### Requirement: 阈值比较语义显式化
引擎 SHALL 以规则函数表达阈值比较：目标线"低于"用严格小于（值==目标不触发）；升级阈值"跌破"默认含等于（值==阈值即升级）。语义须有单元断言固定。

#### Scenario: 等于目标不触发、等于升级阈值触发
- **WHEN** margin 恰好等于目标 18.5 → 不产 p1；华东跌幅恰好等于 -3.0 → 产 e2

### Requirement: 时间戳取自更新事件
洞察证据的 `updated` 与 Pulse 的 `last_updated` SHALL 来自最新 `data_update`；无更新事件时显示 `--`。

#### Scenario: 证据与脉搏时间跟随更新事件
- **WHEN** 最新更新事件时间变化（如 23:59）或事件被清空
- **THEN** `/api/evidence/*.updated` 与 `/api/pulse.last_updated` 反映最新事件时间或 `--`

### Requirement: 洞察语义可来自推理缓存并标注来源
系统 SHALL 将每条洞察的解释语义（semantics）与来源元数据（provider、generated_at）持久化于 `insight_reasoning`；引擎输出洞察时 SHALL 先读取缓存：命中则以缓存语义为准并给出 `reasonSource`/`generatedAt`，未命中则以模板语义回退并标 `reasonSource:"template"`。语义字段结构不得改变。

#### Scenario: 命中缓存的洞察携带来源标注
- **WHEN** 已为某洞察写入 reasoning 缓存后请求 `/api/insights`（或 `/api/insights/{id}`）
- **THEN** 该洞察 `semantics` 等于缓存内容，并带 `reasonSource` 与 `generatedAt`；结构与未命中时一致

#### Scenario: 未命中缓存回退模板且结构不变
- **WHEN** Repository 无该洞察 reasoning 缓存
- **THEN** 语义由模板生成、`reasonSource="template"`，且输出与 V2 基线逐字段一致

### Requirement: LLM 解释可配置且不污染判定
系统 SHALL 在 `DORA_REASONING_PROVIDER=llm` 时使用 OpenAI 兼容接口生成解释；生成结果的 `causeA/causeB` 数值与触发条件 SHALL 始终与引擎一致（LLM 仅允许改写可读文案），未配置 `DORA_LLM_API_KEY` 或调用失败时，对应洞察进入 `fallback` 且引擎输出不回退数据。

#### Scenario: 无 key 时刷新进入 fallback
- **WHEN** `DORA_REASONING_PROVIDER=llm` 且未配置 `DORA_LLM_API_KEY` 调用 `POST /api/reason/refresh`
- **THEN** 返回 `fallback` 覆盖全部洞察、`updated` 为空，且 `/api/insights` 语义仍为模板、判定数值不变

#### Scenario: LLM 只改文案不改数值
- **WHEN** 用确定性 provider mock 返回不同 `causeA.name/next`
- **THEN** 最终缓存 semantics 的 `causeA.value/causeB.value` 与引擎模板一致（数值稳定策略生效）

### Requirement: 数据变更后缓存失效
数据集上传/映射或出厂重置后，`insight_reasoning` SHALL 被清空，使旧解释不再命中。

#### Scenario: 重置样例后缓存清空
- **WHEN** 上传新数据或调用 `/api/datasets/sample`
- **THEN** `insight_reasoning` 行数为 0，后续 `/api/insights` 回退 `reasonSource=template`

### Requirement: 洞察刷新在外部推理服务降级时有界有据
系统 SHALL 在 provider=llm 时对单条 LLM 调用设 ≤10s 超时，并对整批刷新设 ≤20s 预算与 2–3 并发：预算用尽后不再发起新调用，未完成洞察进入 `fallback`；连续 3 次网络级降级失败即中止整批、其余全部 fallback；同一进程 60s 窗口连续失败≥3 触发熔断 30s，熔断期间刷新不发起任何外部调用并立即全量 fallback。刷新 SHALL 按 问题→机会→变化 的优先级消费预算。重复的并发刷新请求 SHALL 合并为一次执行（后到者等待同一结果）。

#### Scenario: 供应商慢/挂起时批量刷新有界
- **WHEN** provider=llm 且外部调用持续超时（网络级降级）
- **THEN** 单条在 ~10s 内失败、连续 3 条后整批中止，剩余洞察全部 `fallback`，刷新总耗时不超过预算+在途尾差（≈30s 内），不出现逐条 40s 的分钟级阻塞

#### Scenario: 熔断开启时不再触网
- **WHEN** 熔断处于 open（60s 窗口 ≥3 次失败后的 30s 内）再次 refresh
- **THEN** 不发起任何外部调用，全部 `fallback` 并快速返回（provider 仍标注 llm）

#### Scenario: 并发刷新合并（单飞）
- **WHEN** 两个请求同时调用 `/api/reason/refresh`
- **THEN** 实际只执行一次 LLM 批量（后到者复用首个请求的结果返回）

### Requirement: 洞察严重等级由数据结构化计算

系统 SHALL 为每条洞察下发 `severity` 字段，等级 SHALL 由数据计算而非模板文案决定：`severity.level` ∈ {`high`, `medium`, `low`}，`severity.score` 为 0–100 的整数，`severity.rule` SHALL 以可读文案说明本次判级口径，`severity.drivers` SHALL 列出参与判级的因子（每项含 `name` 与 `value`，至少一项），`severity.basis` SHALL 固定为 `engine`。判级 SHALL 至少考虑：偏离目标/基线的幅度、连续天数、距阈值距离、影响面（既有快照口径内）。`INSIGHT_TEMPLATES` 的 `tag` 文案 SHALL NOT 参与判级。同一份数据下重复计算的 `severity` SHALL 完全一致。

#### Scenario: 每条洞察都带可解释的等级
- **WHEN** 调用 `GET /api/insights`
- **THEN** 返回的每条洞察均含 `severity`，且 `level` ∈ {high,medium,low}、`score` ∈ [0,100]、`rule` 非空、`drivers` 至少一项、`basis` = `engine`

#### Scenario: 未达阈值的观察项等级不高于已升级问题
- **WHEN** 在同一份数据下比较观察态洞察（`c1`，尚未跌破升级阈值）与问题洞察（`e2`，已跌破升级阈值）
- **THEN** `c1.severity.level` 不高于 `e2.severity.level`，且 `c1.severity.score` 不大于 `e2.severity.score`

#### Scenario: 等级随驱动数据变化
- **WHEN** 驱动信号的数据发生变化（如连续低于目标的天数增加、或距阈值距离缩小）后重新调用 `GET /api/insights/{id}`
- **THEN** 该洞察的 `severity`（`level` 或 `score` 或 `drivers`）随之变化，`tag` 文案保持不变

#### Scenario: 判级数字可回溯且确定
- **WHEN** 检查 `severity.drivers[*].value` 中的数字，并对同一数据源连续计算两次
- **THEN** 这些数字均可在该洞察的引擎 payload（`metric`/`delta`/`desc`/`semantics`/`trigger`）或其快照派生值中找到对应，且两次 `severity` 完全相同

### Requirement: 洞察可能后果由引擎确定性外推

系统 SHALL 为每条洞察下发 `consequence` 字段：`summary`（一句后果判断）、`horizon`（外推观察窗口，如 `3 天`）、`condition`（外推成立条件，如 `若趋势延续`）、`impacts`（受影响项列表，每项含 `name` 与 `value`，至少一项）、`basis`（固定 `engine`）。外推 SHALL 仅使用该洞察同一次计算所用的快照与信号（偏离幅度、连续天数、距阈值距离、影响面等），SHALL NOT 引入快照之外的数字或 LLM 生成的数值。当缺少可用于外推的趋势/阈值字段时，系统 SHALL 输出不含数字的定性后果，而不是臆造数值。同一份数据下重复计算的 `consequence` SHALL 完全一致。

#### Scenario: 每条洞察都带后果与前提
- **WHEN** 调用 `GET /api/insights`
- **THEN** 每条洞察含 `consequence`，其中 `summary`、`horizon`、`condition` 非空，`impacts` 至少一项，`basis` = `engine`

#### Scenario: 后果数字可回溯到快照
- **WHEN** 检查 `consequence.summary` 与 `consequence.impacts[*].value` 中出现的数字
- **THEN** 这些数字均可在该洞察的引擎 payload（`metric`/`delta`/`desc`/`semantics`/`severity`）或其快照派生值中找到对应

#### Scenario: 证据不足时不臆造数值
- **WHEN** 某洞察缺少可用于外推的趋势/阈值字段
- **THEN** 其 `consequence.summary` 为定性表述，且 `impacts[*].value` 不含快照之外的新数字

#### Scenario: 外推确定性
- **WHEN** 同一数据源连续两次调用引擎
- **THEN** 两次返回的每条洞察 `consequence` 完全相同
