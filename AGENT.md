# AGENT.md —— Dora 交接与速查（context 恢复后从这里继续）

> 更新：2026-09-07 ｜ 分支 `main`，HEAD 与 origin/main 同步（最新提交看 `git log -1`）

## 1. 项目是什么
把 v9 单文件 HTML Demo 演进为 **React + FastAPI + PostgreSQL 的 AI 主动经营系统**。判断由确定性引擎（Metric→Rule→Signal→Insight→Evidence）计算；V3 起"解释文案"可接 LLM（默认模板，永不改判定）。

## 2. 单一事实源（去哪查什么）
| 问什么 | 去哪个文件 |
|---|---|
| 现在第几版 / backlog / V3-V5 规划 | `docs/版本路线图.md`（§3A = V3 已完成；**§3B = V4 Watch 已规划待开工**） |
| 迭代历史（每步记录） | `docs/开发过程记录.md`（迭代 0–21） |
| 问题/决策/经验 | `docs/开发问题与经验.md`（P 系列 + D 系列 001–028） |
| 能力 spec（最终态）+ 需求来源表 | `openspec/specs/`（business-engine/business-data-store/data-ingest/upload-mapping） |
| change 导航 + 归档索引 | `openspec/README.md`；归档全量在 `openspec/changes/archive/` |
| V2 / V3 阶段总结 | `RELEASE_NOTES_V2.md` / `RELEASE_NOTES_V3.md` |
| V3 验收清单 | `docs/V3_ACCEPTANCE_CHECKLIST.md`（A/B/C ✅ sign-off ✅） |

## 3. 当前状态
- **V1 ✅ / V2 ✅ / V3 ✅ / V4 已实现待人工验收（Watch）**；迭代 0–27 全归档，`run_all` **6 段**全绿。
- **真实 LLM 已接**：DeepSeek 官方 `deepseek-chat`（backend/.env=llm，本地 git-ignored）；LLM 兜底阶段 1 已落地（P011/D028/D030）。
- 服务运行中：PG(docker `dora-postgres` healthy)、backend :8000（llm 模式）、frontend :5173。

## 4. 下一步（按优先级，任选）
1. **开工 V4-T1（Watch 领域与持久化）**：V4 规划已定（路线图 **§3B** + P/D **D029**），V4-T1..T5 每任务 = 一个 OpenSpec change 按序执行；首个归档 change 新建能力 spec `business-watch`。开工前让用户 review §3B 规划。
2. **LLM 刷新兜底**：**阶段 1 已完成**（迭代 27，P011/D028/D030：超时 10s/预算 20s/并发 3/熔断/优先级/单飞，change `llm-refresh-policy`）。阶段 2 = 异步 job + 状态接口 + 前端"更新中 n/m"+ SSE（待立项）。
3. 可选收尾：路线图"引擎结论与页面数字一致性核对"（低优先）。

## 5. 本地运行 / 验证（新会话先跑）
```bash
docker compose up -d                 # PG16 (dora/dora@5432)
cd backend && python -m app.seed     # 出厂重置（含清 reasoning 缓存）
python3 -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev           # 5173，/api 代理到 8000

cd backend && python3 -m tests.run_all   # 5 段门禁（engine/ingest/reasoning/golden/e2e）
cd frontend && npm run build
python3 /tmp/dora_smoke.py               # 冒烟（需 5173；脚本已绕代理 env）
```
env（backend/.env 样例）：`DATABASE_URL`、`DORA_REASONING_PROVIDER=template`、`DORA_LLM_BASE_URL/API_KEY/MODEL`。

## 6. 代码地图（改哪找哪）
| 关注点 | 文件 |
|---|---|
| 引擎判定 | `backend/app/engine/engine.py`（rules/snapshot/evidence），`engine/dataset.py`（纯种子源） |
| 数据层 | `backend/app/{models,repository,db,seed}.py` |
| 上传/映射 | `backend/app/ingest.py`、`backend/app/routers.py`（/datasets*, /reason/refresh） |
| V3 推理 | `backend/app/reasoning/{provider,semantics,cache,llm}.py` |
| 前端 | `frontend/src/App.tsx`、`features/*`、`services/doraApi.ts`（三模式 API）、`data.ts`（本地兜底/种子镜像） |
| 测试 | `backend/tests/`（engine/ingest/reasoning/golden/e2e/run_all） |

## 7. 工作流规则（务必遵守，见 .clinerules/project-conventions.md）
- 单一事实源：待办/版本只改路线图；开发记录只追加"迭代 N"；经验只进 P/D。
- 代码改动（feature/fix）必须归属一个 OpenSpec change：`openspec new change <kebab>` → proposal/spec/design/tasks → validate → **propose 关键取舍即时记 D 系列** → 用户 review 后 apply → 逐任务勾选+验证 → archive（含【测试证据】+【反思】）→ 同步路线图/dev-log/P-D。
- docs/chore 可直提；提交信息中文 `feat/fix/docs/chore`；push 遇 SSL 抖动用 `GIT_HTTP_VERSION=HTTP/1.1 git push`。
- 任务"完成"判据：run_all(5 段) + build + 相关端点 curl（绕代理 env）+ 冒烟。

## 8. 未决/注意（重要上下文）
- **P011/D028/D030**：LLM 刷新兜底 **阶段 1 已落地**（迭代 27：单条 10s/整批预算 20s/并发 3/熔断/优先级/单飞，reasoning 实测 9 条 4.9s）；**阶段 2（异步 job/SSE + 前端进度）待立项**。
- V4 misc："引擎结论与页面数字一致性核对"仍未做（低优先）；图表仍为前端展示层静态。
- **真实 LLM 已配置**：DeepSeek 官方 `deepseek-chat`（backend/.env 本地，git-ignored），`DORA_REASONING_PROVIDER=llm`；reasoning/run_all 门禁已自行钉死 template+空 key 环境，不受本地配置影响。
- spec 导航把 V3 三条需求已并入 business-engine（14 条），README 索引 13 个 change。
