## MODIFIED Requirements

### Requirement: 委托经 REST 可管理并回显到界面

系统 SHALL 暴露 watch REST：创建（文本委托 + 频率 → 解析 → 落库 → 即时评估）、列表（含最新状态与**委托生命周期回显字段**）、单查（含命中事件）、暂停/恢复、删除（级联事件）、手动检查。列表条目与创建/暂停响应中的委托卡片 SHALL 回显：解析后的 `intent`（指标/范围/条件/频率，与解析结果一致）、`lastCheckedAt`（最近一次评估时刻）与 `lastEvent`（最近一次命中事件 `{kind: change|escalate, summary, triggeredAt}`；无命中时为 `null`），使前端无需再查详情即可回显「委托走到哪一步」。前端 Watch 页 SHALL 以该接口为真实数据源（输入解析回显 → 确认创建 → 列表操作），Pulse「持续关注」计数与最近状态 SHALL 来自真实委托列表而非静态数组。前端右侧「Dora 接到委托后会做什么」流程 SHALL 由真实委托状态驱动（理解目标 → 匹配数据口径 → 持续检查 / 已暂停 → 命中回脉搏 / 引擎判定升级），SHALL NOT 展示与真实委托状态不符的步骤态。后端不可用时前端才回退本地演示数据并标注静态，且该流程 SHALL 只推进到本地已知步骤（理解目标 / 匹配口径），其余步骤显式标注需连接后端。

#### Scenario: 委托创建与即时评估

- **WHEN** POST /api/watch 提交"帮我关注华东销售额，如果连续三天下降就提醒我"
- **THEN** 返回创建的 target（含解析 intent），且创建后立即做一次评估；再次 GET 列表可见该委托且状态/频率/最近检查时间已更新

#### Scenario: 暂停后不评估

- **WHEN** PATCH 将委托 status=paused 后数据更新触发即时评估
- **THEN** 该委托不被评估、不产生新事件；恢复 watching 后才恢复评估

#### Scenario: 卡片回显委托生命周期字段

- **WHEN** 创建一条委托（无命中）后 GET /api/watch，随后该委托命中一次并再次 GET /api/watch
- **THEN** 两次读回的卡片均含 `intent`（`metric_key`/`dimension`/`condition` 与解析结果一致）与 `lastCheckedAt`；命中前 `lastEvent` 为 `null`，命中后 `lastEvent.kind` ∈ {change, escalate} 且 `summary` 非空

#### Scenario: 流程面板与真实委托状态一致

- **WHEN** 前端在同一会话内依次经历「未输入委托 → 让 Dora 理解成功 → 开始持续关注 → 命中（含引擎判定升级）→ 暂停」
- **THEN** 面板依次呈现：待命（无步骤完成）→ 步骤 1/2 完成（展示真实指标/范围/条件与引擎口径）→ 步骤 3 进行中（真实频率 + 最近检查时刻）→ 步骤 4 命中（`kind=change` 展示事件 summary）/ 已升级（`kind=escalate` 文案引用引擎判定）→ 暂停后步骤 3 显式「已暂停 · 不评估」且步骤 4 不再显示为进行中

#### Scenario: 离线不伪造流程状态

- **WHEN** 后端不可用（列表回退本地演示数据）
- **THEN** 面板只推进本地已知的步骤 1/2，步骤 3/4 显式标注需连接后端，且页面标注「离线演示」；不出现"持续检查中 / 已命中 / 已升级"等未真实发生的状态
