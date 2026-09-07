## ADDED Requirements

### Requirement: 委托经 REST 可管理并回显到界面
系统 SHALL 暴露 watch REST：创建（文本委托 + 频率 → 解析 → 落库 → 即时评估）、列表（含最新状态）、单查（含命中事件）、暂停/恢复、删除（级联事件）、手动检查。前端 Watch 页 SHALL 以该接口为真实数据源（输入解析回显 → 确认创建 → 列表操作），Pulse「持续关注」计数与最近状态 SHALL 来自真实委托列表而非静态数组；后端不可用时前端才回退本地演示数据并标注静态。

#### Scenario: 委托创建与即时评估
- **WHEN** POST /api/watch 提交"帮我关注华东销售额，如果连续三天下降就提醒我"
- **THEN** 返回创建的 target（含解析 intent），且创建后立即做一次评估；再次 GET 列表可见该委托且状态/频率/最近检查时间已更新

#### Scenario: 暂停后不评估
- **WHEN** PATCH 将委托 status=paused 后数据更新触发即时评估
- **THEN** 该委托不被评估、不产生新事件；恢复 watching 后才恢复评估
