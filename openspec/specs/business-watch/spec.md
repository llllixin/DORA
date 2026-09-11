# business-watch Specification

## Purpose
Dora"持续关注（Watch）"能力的行为契约：用户以一句话把业务目标委托给 Dora（WatchTarget：指标/范围/条件/频率），系统按频率或数据更新评估并持久化命中事件（WatchEvent），把变化送回业务脉搏并按条件升级——本能力保证委托与命中记录可持久化存取、可追溯，为"委托→评估→事件→回脉搏"闭环提供数据层契约（判定仍由确定性引擎负责，Watch 不伪造 problem/opportunity 身份）。

## 需求来源表（Traceability）

| 需求 | 由谁新增 | 归档 change | 迭代 |
|---|---|---|---|
| 委托与命中事件可持久化存取 | V4-T1 Watch 领域 | `changes/archive/2026-09-07-v4-watch-domain` | 22 |
| 委托语句可解析为结构化委托（显式确认） | V4-T2 委托解析 | `changes/archive/2026-09-07-v4-watch-parser` | 23 |
| 委托被自动评估并记录命中事件（不伪造身份） | V4-T3 评估器 | `changes/archive/2026-09-07-v4-watch-evaluator` | 24 |
| 委托经 REST 可管理并回显到界面 | V4-T4 Watch UI | `changes/archive/2026-09-07-v4-watch-ui` | 25 |
| 委托经 REST 可管理并回显到界面（卡片回显生命周期字段 + 流程面板状态驱动 + 离线不伪造） | 迭代45 持续关注页收口 | `changes/archive/2026-09-11-watch-delegate-flow` | 45 |

## Requirements

### Requirement: 委托与命中事件可持久化存取
系统 SHALL 提供 `watch_target` 与 `watch_event` 的持久化：一个 watch target 记录"原始委托语句 + 解析结果（metric_key/dimension/condition/frequency）"与当前状态（watching|paused）；一个 watch event 记录某次命中（时刻/kind=change|escalate/文案/前后值），并归属且仅归属一个 target。Repository SHALL 支持创建、列表、单查、改状态、删除（删除级联清理其全部事件）与整体清空原语，数据库不可用时与现有读接口一致抛"数据源不可用"。

#### Scenario: CRUD 往返保留委托与状态
- **WHEN** 创建一条 watch target（含解析结果 JSON、status=watching、frequency=on_update），随后列表、按 id 单查、暂停（paused）后再单查
- **THEN** 各次读回的结构化字段与写入一致，暂停后 status=paused；不存在的 id 单查返回空（不抛错）

#### Scenario: 命中事件级联与删除
- **WHEN** 对同一 target 追加 change 与 escalate 两类事件后删除该 target
- **THEN** 事件列表按序返回该 target 的两条事件；删除后 target 与其全部事件均不可再查（幂等，重复删除不抛错）

### Requirement: 委托语句可解析为结构化委托（显式确认）
系统 SHALL 提供解析入口：把中文委托语句（"关注什么指标/范围，什么条件下提醒"）解析为结构化 intent（`metric_key`、`dimension`、`condition{type,days?,ref?,ref_is_pct?}`、`frequency?`、显示 `label`）；仅当指标命中引擎受支持的词典时才返回 `ok=true`，否则 `ok=false` 且返回 `unsupported`（原因：不支持的指标/未识别），绝不静默假设成别的指标。未识别触发条件时 SHALL 返回建议默认"连续 3 天下降"并标记 `condition_defaulted=true`（供确认界面展示，不隐藏）。

#### Scenario: 支持句式解析成功
- **WHEN** 解析 "帮我关注华东销售额，如果连续三天下降就提醒我"
- **THEN** `ok=true`，intent 为 `metric_key=east_orders, dimension=华东, condition={type:streak_below,days:3}, label=华东销售额`

#### Scenario: 值跌破与频率词
- **WHEN** 解析 "关注利润率，跌破 18% 就提醒我，每天 09:00 检查"
- **THEN** `ok=true`，intent `condition={type:below,ref:18.0,ref_is_pct:true}`，`frequency=daily 09:00`，`condition_defaulted=false`

#### Scenario: 不支持的指标显式拒绝
- **WHEN** 解析 "关注库存周转，连续 3 天下跌就提醒我"
- **THEN** `ok=false`，`intent=null`，`unsupported` 含该指标与"暂不支持/可用指标"提示

### Requirement: 委托被自动评估并记录命中事件（不伪造身份）
系统 SHALL 按委托的条件（连续 N 天下降/上涨、跌破/超过 X）对引擎受支持指标求值，命中时写 `watch_event`（kind=change），相同结果不重复写；评估时机 SHALL 覆盖"数据更新/样例重置成功后即时"与"进程内周期调度（每日 09:00 / 每周）"。只有当引擎已判定该指标对应 problem/opportunity 洞察时，事件 kind SHALL 升级为 escalate 并在 values 中引用该引擎 insight id——Watch 不自行断言 problem/opportunity 身份。

#### Scenario: 数据更新即时评估命中并去重
- **WHEN** 注入连续下跌序列后调用评估（on_update 触发），随后再次评估同一数据
- **THEN** 首次命中写入一条 change 事件；再次评估不重复写（去重命中），且 last_checked_at 被更新

#### Scenario: 升级事件仅引用引擎判定
- **WHEN** 委托 east_orders（连续下跌）且数据跌破引擎升级阈值使 run_engine 产出 problem `e2`
- **THEN** 事件 kind=escalate 且 `values.engine_insight=="e2"`；无引擎判定时任何指标都不会产生 escalate

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
