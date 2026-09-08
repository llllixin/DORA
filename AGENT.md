# AGENT.md —— Dora 交接与速查（context 恢复后从这里继续）

> 更新：2026-09-08 ｜ 分支 `main`（最新提交看 `git log -1`；本拆分为 docs 提交）

## 1. 项目是什么
把 v9 单文件 HTML Demo 演进为 **React + FastAPI + PostgreSQL 的 AI 主动经营系统**。判断由确定性引擎（Metric→Rule→Signal→Insight→Evidence）计算；V3 起"解释文案"可接 LLM（默认模板，永不改判定）。

## 2. 单一事实源（去哪查什么）
| 问什么 | 去哪个文件 |
|---|---|
| 当前状态 / 现在是第几版 | `docs/版本路线图.md`（V1–V5 ✅ sign-off；无打开的版本，不预命名 V6） | 版本状态入口 |
| 已完成版本历史（V1–V5） | `docs/历史版本路线.md` | 归档，不再改动状态 |
| 未解决 / 候选 / backlog | `docs/持续优化路线.md` | **唯一 backlog**（3D.1 W1–W3、3D.2 E1–E3、遗留小项 §2、审查遗留 §5） |
| 迭代历史（每步记录） | `docs/开发过程记录.md`（迭代 1–38） |
| 问题/决策/经验 | `docs/开发问题与经验.md`（P 系列 + D 系列 001–034） |
| 能力 spec（最终态）+ 需求来源表 | `openspec/specs/`（6 个能力：business-engine/business-data-store/data-ingest/upload-mapping/business-watch/business-action） |
| change 导航 + 归档索引 | `openspec/README.md`；归档全量在 `openspec/changes/archive/` |
| V2 / V3 / V4 / V5 阶段总结 | `RELEASE_NOTES_V2.md` / `RELEASE_NOTES_V3.md` / `RELEASE_NOTES_V4.md` / `RELEASE_NOTES_V5.md` |
| V5 验收清单 | `docs/V5_ACCEPTANCE_CHECKLIST.md`（A/B/C ✅ sign-off ✅，V5 已完成） |
| 优化方向 / 审计清单 | `docs/优化方向.md`（2026-09-07 全流程审计：F1–F11 + P0/P1/P2 候选） |
| V3 验收清单 | `docs/V3_ACCEPTANCE_CHECKLIST.md`（A/B/C ✅ sign-off ✅） |

## 3. 当前状态
- **V1 ✅ / V2 ✅ / V3 ✅ / V4 ✅ / V5 ✅（Action 真闭环，sign-off 完成）**——五个版本全部完成；V5 后收尾迭代 34–38 亦已归档，`run_all` **7 段** ALL GREEN（golden 9 不变）、`npm run build` 绿。
- **V5 之后 = 候选方向 + 两块 backlog（不占版本号）**：候选清单见 `docs/持续优化路线.md` §1；已选 backlog（3D.1 前端接线收口 W1–W3 / 3D.2 专家团领域化 E1–E3）见 §3–§4；已完成收尾见 `docs/历史版本路线.md` §5。另立版本需先在持续优化路线写规划块。
- **真实 LLM 已接**：DeepSeek 官方 `deepseek-chat`（backend/.env=llm，本地 git-ignored）；LLM 兜底阶段 1 已落地；前端 refresh 超时 Bug1 已收口（30s）。
- 服务运行中：PG(docker `dora-postgres` healthy)、backend :8000（llm 模式）、frontend :5173。

## 4. 下一步（顺序与范围以 `docs/持续优化路线.md` 为准）
0. **Phase 0 收口（审查遗留 §5）**：A1–A3 合并 change `knowledge-lifecycle`（knowledge/lesson 级联 + verify 单事务 + archive 列放宽）→ B1（run_all 用 `sys.executable`）→ 清理演示库 o2 矛盾残留。
1. **3D.1 W1/W2**：`frontend-loop-pulse` / `frontend-loop-insight`（可并行；proposal 须含离线镜像迁移 + 字段盘点两项补强）。
2. **3D.2 E1→E2→W3/E3**：`expert-registry-domain` → `expert-registry-orchestration` → W3/E3 汇合（回归锚点 ≥8 段）。
3. **候选方向（§1）**：LLM 兜底阶段 2（异步 job + 状态接口 + SSE）、工具/Agent 执行层（D031-1 预留口）、Docker 全家桶（搭建文档 37）、Redis/Celery（D009 推迟项）。
4. 维护跟踪：引擎结论与页面数字一致性核对收尾、AskBar/Dora Chat 追问 mock（F8）——均见 `持续优化路线.md` §2。

## 5. 本地运行 / 验证（新会话先跑）
```bash
docker compose up -d                 # PG16 (dora/dora@5432)
cd backend && python -m app.seed     # 出厂重置（含清 reasoning 缓存）
python3 -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev           # 5173，/api 代理到 8000

cd backend && python3 -m tests.run_all   # 7 段门禁（engine/ingest/reasoning/golden/e2e/watch/action）
cd frontend && npm run build
python3 /tmp/dora_smoke.py               # 冒烟（需 5173；脚本已绕代理 env）
```
- **依赖解释器**：本机依赖在 `/Users/tomara/miniforge3/bin/python3`（含 sqlalchemy/fastapi/psycopg）；默认 `python3`（homebrew）缺依赖会使 run_all 全红，请先激活对应环境或把 miniforge bin 置于 PATH 最前。
env（backend/.env 样例）：`DATABASE_URL`、`DORA_REASONING_PROVIDER=template`、`DORA_LLM_BASE_URL/API_KEY/MODEL`。

## 6. 代码地图（改哪找哪）
| 关注点 | 文件 |
|---|---|
| 引擎判定 | `backend/app/engine/engine.py`（rules/snapshot/evidence），`engine/dataset.py`（纯种子源） |
| 数据层 | `backend/app/{models,repository,db,seed}.py` |
| 上传/映射 | `backend/app/ingest.py`、`backend/app/routers.py`（/datasets*, /reason/refresh, /pulse, /insights, /evidence, /watch, /action, /knowledge） |
| V3 推理 | `backend/app/reasoning/{provider,semantics,cache,llm}.py` |
| V4 Watch | `backend/app/watch/{parser,evaluator,scheduler}.py` |
| V5 Action / 经验 / 知识 | `backend/app/action/{builder,flow}.py`、models `CaseLesson`/`KnowledgeArchive` + Repository 对应方法 |
| 前端 | `frontend/src/App.tsx`、`features/{pulse,insight,action,watch,knowledge,onboarding}`、`services/doraApi.ts`（三模式 API）、`data.ts`（离线镜像/演示兜底） |
| 测试 | `backend/tests/`（engine/ingest/reasoning/golden/e2e/watch/action + llm_real_smoke + run_all） |

## 7. 工作流规则（务必遵守，见 .clinerules/project-conventions.md）
- 单一事实源：当前状态→`版本路线图.md`；版本历史→`历史版本路线.md`；待办/backlog→`持续优化路线.md`（只改那一处）；开发记录只追加"迭代 N"；经验只进 P/D。
- 代码改动（feature/fix）必须归属一个 OpenSpec change：`openspec new change <kebab>` → proposal/spec/design/tasks → validate → **propose 关键取舍即时记 D 系列** → 用户 review 后 apply → 逐任务勾选+验证 → archive（含【测试证据】+【反思】）→ 同步持续优化路线勾选 / dev-log 追加 / P-D 落档。
- docs/chore 可直提；提交信息中文 `feat/fix/docs/chore`；push 遇 SSL 抖动用 `GIT_HTTP_VERSION=HTTP/1.1 git push`。
- 任务"完成"判据：run_all(7 段) ALL GREEN + build + 相关端点 curl（绕代理 env）+ 冒烟。

## 8. 未决/注意（重要上下文）
- **P011/D028/D030**：LLM 刷新兜底 **阶段 1 已落地**（迭代 27：单条 10s/整批预算 20s/并发 3/熔断/优先级/单飞）；**阶段 2（异步 job/SSE + 前端进度）在 `持续优化路线.md` §1 候选**。
- **知识库两处易踩**：① knowledge_archive/case_lesson 删除不级联，基线恢复会留孤儿行（A1，演示库 o2 曾有矛盾实例）；② `ActionCase.archive` 为 VARCHAR(500)，多轮 continue/长 note 追加会触发 PG 报错（A3）——均列入 `持续优化路线.md` §5 待 `knowledge-lifecycle` 收口。
- **真实 LLM 已配置**：DeepSeek 官方 `deepseek-chat`（backend/.env 本地，git-ignored），`DORA_REASONING_PROVIDER=llm`；run_all 门禁已自行钉死 template+空 key 环境，不受本地配置影响。能力 spec 共 6 个、README 归档索引 30 个 change、dev-log 迭代 1–38。
