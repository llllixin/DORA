## ADDED Requirements

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
