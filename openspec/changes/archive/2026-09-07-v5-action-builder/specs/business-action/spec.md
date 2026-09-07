## ADDED Requirements

### Requirement: 引擎判定的洞察可建档为行动档案（幂等）
系统 SHALL 提供建档：把引擎判定的 problem/opportunity 洞察转成 action_case（id=insight_id）与步骤集（发现=done、定位/拆解=in_progress、验证=待办、归档=待办；desc/evidence 引用洞察的 trigger/metric/delta 等事实）。建档 SHALL 仅接受"当前引擎判定集内"的 problem/opportunity 洞察：change 洞察、watch escalate 事件与伪造 id 一律拒绝；同洞察重复建档返回既有档案（created=False），不产生第二份。

#### Scenario: 新 problem（如跌破升级 e2）建档成功且幂等
- **WHEN** 注入跌破阈值数据使引擎产出 problem e2 后调用建档
- **THEN** 返回 created=True 的新档案（kind=problem、code 前缀 PRB-、4 步模板、首步 done）；再次建档返回同一档案且 created=False

#### Scenario: 非判定/change/伪造不建档
- **WHEN** 用 change 洞察、watch escalate 假身或引擎判定集之外的 id 调用建档
- **THEN** 抛 ValueError，不写任何行
