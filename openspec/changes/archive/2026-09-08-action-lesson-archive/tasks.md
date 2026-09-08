## 1. 后端经验沉淀

- [x] 1.1 `models.py` 增 `CaseLesson`（case_id pk、code/kind/title/archive/resolution/created_at）；`repository.py`：`create_case_lesson(case_id, note)`（仅 resolved 可由调用方 guard；同 id 已有返回既有；返回 dict）/`list_case_lessons()`/`delete_case_lesson(id)` 测试自清/`count_rows` 补映射；验证：action_check 第 5 节
- [x] 1.2 `routers.py`：`POST /api/action/cases/{id}/archive-as-lesson {note}`（非 resolved→400、缺 case→404、note 空→400）与 `GET /api/action/lessons`；schemas 增 `ArchiveLessonRequest`；验证：见 1.3 冒烟与 action_check

## 2. 前端抽屉布局 + 归档经验

- [x] 2.1 types `CaseLesson`；doraApi `archiveAsLesson(id,note)`、`listLessons()`；验证：`npm run build`
- [x] 2.2 ActionPage 重构：档案列表=可收起抽屉（默认窄列+竖向 tab），主区流程/验证/归档占大布局；resolved 视图含「沉淀经验」按钮（成功后显示"已加入经验库"）与处理过程；抽屉底部「学习经验 n」展开最近经验；demo 分支保持可用；验证：build + 页面冒烟

## 3. 测试与收尾

- [x] 3.1 `tests/action_check.py` 第 5 节「经验沉淀」：resolved→archive-as-lesson created→重复幂等→list 含→running 拒绝 400→清理；`python3 -m tests.action_check` ALL GREEN
- [x] 3.2 回归：`python3 -m tests.run_all` **7 段 ALL GREEN**；golden 9 不变；npm build
- [x] 3.3 dev-log「迭代 36」+ D033 + archive（【测试证据】+【反思】）

【测试证据】action_check（第 1–5 节）ALL GREEN（经验沉淀：resolved→create created→幂等 created=False→list 含→delete 幂等）；run_all 连跑两次均 ALL GREEN（7 段, golden 9 不变）；npm run build ✅；API 冒烟：running 归档→400「仅已归档…」、resolve o1→archive created=True（UPC-0418）→重复 False→lessons 200 含 o1。
【反思】“自我学习”落地为确定性经验沉淀（CaseLesson）+ 用户可见问题归档（archive 处理过程），不夸大模型学习；resolved-only 权限与幂等由端点 guard + case_id 主键双保险；布局抽屉化让流程主区占多数，drawer 折叠保留快速切换。

