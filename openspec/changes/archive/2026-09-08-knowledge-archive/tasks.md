## 1. 后端知识库

- [x] 1.1 `models.py` 增 `KnowledgeArchive`（唯一 (entry_type,source_id)）；`repository.py`：add_knowledge/list(entry_type?)/delete_by_source/count_rows；验证：见 1.3
- [x] 1.2 写入钩子：`flow.verify` resolved→add（entry_type=case.kind）；`repo.create_case_lesson` 同事务补 lesson 行；`routers.py` 增 `GET /api/knowledge?type=`（entries+stats）
- [x] 1.3 `tests/action_check.py` 第 6 节：resolved→knowledge problem 行；沉淀经验→lesson 行；重复幂等；type 筛选与 stats；清理；`python3 -m tests.action_check` ALL GREEN

## 2. 前端知识库

- [x] 2.1 types `KnowledgeEntry/KnowledgeStats`；doraApi `listKnowledge(type?)`；`npm run build`
- [x] 2.2 新增 `features/knowledge/KnowledgePage.tsx` + Sidebar「◈ 知识库」+ App 接入 Page 'knowledge'；类型 chips（带计数）+ 条目卡片（code/title/content/note/时间）；空态

## 3. 收尾

- [x] 3.1 回归：run_all **7 段 ALL GREEN**；golden 9 不变
- [x] 3.2 dev-log「迭代 38」+ archive（【测试证据】+【反思】）

【测试证据】action_check（第 1–6 节）ALL GREEN：resolved→knowledge problem/opportunity 行、沉淀经验→lesson 行、重复 lesson 幂等不新增、type 筛选/stats、测试残留自清；run_all ALL GREEN（7 段, golden 9 不变）；npm run build ✅；API 冒烟：stats {problem:1, lesson:1}、?type=problem 过滤、?type=lesson 命中、清理后归零。
【反思】knowledge_archive 作为统一归档视图、case_lesson 为经验引用视图（双表冗余留未来合并取舍）；写入点放在语义发生处（flow.verify resolved / create_case_lesson 同事务）保证一致性；测试自持 seed 基线（F4 后 sample 不归零）避免环境依赖。

