# Dora · V5 Release Notes（Action 真闭环）

> 发布日期：2026-09-07 ｜ 验收：✅ sign-off（docs/V5_ACCEPTANCE_CHECKLIST.md）
> 一句话：**把"加入行动回路"从静态页面升级为可追溯的 Case 状态机**——引擎判定的洞察一键建档 → 步骤执行（start/done/blocked + 回填）→ 验证（resolved 归档 / continue 继续观察）→ 档案回写；结果决定关闭，回写不污染引擎判定。

## 1. V5 交付（迭代 28–33，全部 OpenSpec 归档）
| 任务 | 交付 |
|---|---|
| T1 领域与持久化 | `action_case`/`action_step` 表 + Repository CRUD + **5 例静态 ACTIONS 迁移 seed**（保留 PRF-0831 等档案编号） |
| T2 建档引擎 | `app/action/builder.py`：仅当前引擎判定 problem/opportunity 可建档（change/watch escalate/伪造拒绝）；按 insight 幂等；4 步模板 + 确定性 code |
| T3 状态机 API | `flow.py`（合法性唯一真源）+ `/api/action/cases` REST；start/done/blocked/verify；resolved 冻结一切迁移（4xx） |
| T4 前端真实化 | ActionPage 消费真档案（步骤控件/验证区/归档视图）；洞察「加入行动回路」=真建档（离线才 demo 兜底） |
| T5 验收收尾 | Case 1/2/4 Action 段闭环 E2E（HTTP）入 action_check 第 4 节；V5 验收清单 + sign-off |

## 2. 核心语义
```text
引擎判定 problem/opportunity
  → POST /action/cases（幂等：同洞察一条档案）
  → steps：发现 done → 定位 in_progress → 验证 pending → 归档 pending
  → start/done/blocked（note/result 回填；全 done → waiting_verify）
  → verify resolved（需验证说明，追加 archive）/ continue（→ running）
红线：resolved 只认 verify；档案回写不改引擎判定/reasonSource；watch escalate 不自动建档。
```

## 3. 接口
`POST /api/action/cases`（insight_id 建档）、`GET /api/action/cases[/{id}]`、`POST …/steps/{seq}/start|done|blocked`、`POST …/verify`（旧 `/api/actions` 静态端点待清理候选）。

## 4. 质量与验收
- run_all **7 段** ALL GREEN（action_check 4 节：领域/建档/状态机/闭环 E2E）✅；golden 9 不变；npm build ✅
- 人工验收 C 段 ✅ + sign-off（2026-09-07）→ V5 标完成

## 5. V1–V5 里程碑达成
五个版本（搭建文档第 30–34 章）全部完成：可运行 → 真实业务分析 → Reasoning → Watch 委托 → Action 闭环。

## 6. 下一步（候选方向，未入版本规划）
见 docs/版本路线图.md §3C.6：工具/Agent 执行层、Redis/Celery 调度、SSE/异步任务（LLM 兜底阶段 2）、多数据源、Docker 全家桶、生产部署。另立正式版本须先 §3D backlog/planning。
