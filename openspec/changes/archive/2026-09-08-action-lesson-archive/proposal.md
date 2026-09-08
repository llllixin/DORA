# action-lesson-archive

## Why

V5 已验证"结果决定关闭"，但归档后经验只躺在 archive 文案里，用户看不到全局处理过程，系统也不能在未来复用。本次把 Action 闭环收尾做成产品级：resolved 后一键**归档**（问题档案，含可读处理过程），并把其中可复用的**经验沉淀进 DB（CaseLesson 经验库）**——"自我学习"采用确定性沉淀与检索（不训练模型），未来相似洞察可直接引用这些经验。

## What Changes

- **布局抽屉化**：ActionPage 左侧档案列表收成**可收起抽屉**（默认展开为窄列，可折叠成竖向 tab）；**流程主区占据大部分布局**（步骤时间线/备注结果/验证区）。
- **归档两步**：
  1. 流程完成→验证 resolved→显示**已归档视图**（archive 含验证记录=给用户看的处理过程）；
  2. 按钮「沉淀经验」→ `POST /api/action/cases/{id}/archive-as-lesson`（仅 resolved 可归档，幂等）→ 写入 `case_lesson` 经验库。
- **经验库可见**：抽屉底部「学习经验 N 条」→ 展开最近经验列表（问题/处理/结论）供用户与未来引用查看。
- 后端：`CaseLesson` 表 + Repository（create-if-absent/list）+ REST（archive-as-lesson、GET /api/action/lessons）。

## Capabilities

### Modified Capabilities
- `business-action`: resolved 档案可一键沉淀为可复用经验（CaseLesson）并形成用户可见的问题归档；经验库只存确定性处理记录，不改变判定语义。

## Impact

- 后端：models/repository/routers/tests(action_check 第 5 节)；前端：types/doraApi/ActionPage 布局重构 + 归档经验 UI；docs：D033、dev-log 迭代 36。
- 验证：action_check 第 5 节（仅 resolved 可沉淀/幂等/list）；run_all 7 段 ALL GREEN；npm build。
