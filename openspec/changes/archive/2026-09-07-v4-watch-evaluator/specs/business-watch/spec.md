## ADDED Requirements

### Requirement: 委托被自动评估并记录命中事件（不伪造身份）
系统 SHALL 按委托的条件（连续 N 天下降/上涨、跌破/超过 X）对引擎受支持指标求值，命中时写 `watch_event`（kind=change），相同结果不重复写；评估时机 SHALL 覆盖"数据更新/样例重置成功后即时"与"进程内周期调度（每日 09:00 / 每周）"。只有当引擎已判定该指标对应 problem/opportunity 洞察时，事件 kind SHALL 升级为 escalate 并在 values 中引用该引擎 insight id——Watch 不自行断言 problem/opportunity 身份。

#### Scenario: 数据更新即时评估命中并去重
- **WHEN** 注入连续下跌序列后调用评估（on_update 触发），随后再次评估同一数据
- **THEN** 首次命中写入一条 change 事件；再次评估不重复写（去重命中），且 last_checked_at 被更新

#### Scenario: 升级事件仅引用引擎判定
- **WHEN** 委托 east_orders（连续下跌）且数据跌破引擎升级阈值使 run_engine 产出 problem `e2`
- **THEN** 事件 kind=escalate 且 `values.engine_insight=="e2"`；无引擎判定时任何指标都不会产生 escalate
