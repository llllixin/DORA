## ADDED Requirements

### Requirement: 已归档档案可沉淀为经验库并展示处理过程
系统 SHALL 提供"沉淀经验"：对 status=resolved 的行动档案调用归档接口后，将 `case_lesson` 记录（case 编号/类型/标题/处理过程 archive/结论 note/时间）写入经验库；同一档案重复沉淀幂等（返回既有）；非 resolved 档案调用 SHALL 被拒绝（4xx）。系统 SHALL 提供经验列表查询（按时间倒序），供用户查看"处理过程"与未来相似洞察引用。

#### Scenario: resolved 后沉淀经验且幂等
- **WHEN** 档案已 resolved，先 POST archive-as-lesson 再重复 POST
- **THEN** 首次写入经验库（created=True），重复调用返回既有且经验条数不变

#### Scenario: 未完成档案拒绝沉淀
- **WHEN** 对 running/waiting_verify 档案调用 archive-as-lesson
- **THEN** 返回 4xx 且经验库无新增
