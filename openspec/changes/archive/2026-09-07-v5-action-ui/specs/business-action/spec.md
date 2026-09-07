## ADDED Requirements

### Requirement: 档案可在界面真实执行与验证（真数据源）
系统 SHALL 让 Action 页从 /api/action/cases 读取档案列表与详情，并按步骤状态展示推进控件（pending|blocked→开始、in_progress→完成/阻塞、waiting_verify→验证区（归档需填写验证说明 / 继续观察）、resolved→已归档视图）。洞察页的「加入行动回路」SHALL 对当前引擎判定的 problem/opportunity 调用建档接口（幂等返回既有档案），接口拒绝（400）时向用户展示原因且不伪造本地加入；仅当后端不可用时回退本地演示数据并标注。

#### Scenario: 建档入口真实落库
- **WHEN** 在洞察详情点击「加入行动回路」（problem/opportunity，后端在线）
- **THEN** 创建/返回既有档案，页面跳转行动页可见该档案；若该洞察不在当前引擎判定集则显示后端原因而非伪造成功

#### Scenario: 步骤与验证控件真实驱动状态机
- **WHEN** 对档案详情执行「开始/完成/阻塞/归档(带说明)」
- **THEN** 界面调用对应 /api/action/cases 端点并刷新展示最新状态/note/result/归档视图；非法迁移由后端 4xx 拒绝并在界面提示
