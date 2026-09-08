# OpenSpec 导航（Dora）

> 用 OpenSpec 组织"需求（capability spec）与变更（change）"。这里是**查找入口**。

## 布局

| 目录 | 放什么 | 何时看 |
|---|---|---|
| `openspec/specs/<capability>/spec.md` | **能力最终态 spec**（收敛：6 个文件） | 想知道"系统现在必须做到什么" |
| `openspec/changes/<id>/` | 活跃中的变更（propose→apply） | 当前在做什么 |
| `openspec/changes/archive/<date>-<id>/` | **已归档变更全量**（proposal/spec/design/tasks） | 想追"某个需求的来龙去脉/逐任务细节" |
| `.clinerules/workflows` + `.cline/skills` | propose/apply/update/archive 工作流 | 流程操作 |

## 查找三步
1. **系统要什么** → `openspec/specs/`（6 个能力：business-engine / business-data-store / data-ingest / upload-mapping / business-watch / business-action）。
2. **某条需求谁加的/验证证据** → 打开对应 spec，顶部「需求来源表」给出 change 归档目录与迭代号。
3. **逐任务细节** → 进 `openspec/changes/archive/<date>-<id>/tasks.md`（每条任务含验证命令），proposal=为什么、design=怎么做。

## 归档 Change 索引（29 个）
| Change | 归档目录（date-<id>） | 影响的 spec（+需求数） | 迭代 | 备注/决策 |
|---|---|---|---|---|
| C1 引擎覆盖 | 2026-09-07-extend-engine-coverage | business-engine +3 | 9 | 基线建 spec |
| C2 PostgreSQL | 2026-09-07-postgres-repository | business-data-store +3 / business-engine +2 | 10 | D016 |
| c3 证据修复 | 2026-09-07-fix-new-sku-evidence | business-engine +1 | 11 | P009 |
| C3 真实上传 | 2026-09-07-dataset-upload | data-ingest +2 / business-engine +1 | 12 | D017 |
| C4 列映射 | 2026-09-07-upload-mapping | upload-mapping +2 | 13 | D018 |
| C5 E2E 门禁 | 2026-09-07-e2e-guardrails | business-engine +1 | 14 | D019 |
| 收尾清理 | 2026-09-07-code-cleanup | skip_specs（0） | 15 | D020 |
| V2 边界修复 | 2026-09-07-fix-v2-critical-boundaries | business-engine +3 | 16 | D021/P010 |
| V3-T1 推理抽象层 | 2026-09-07-v3-reasoning-layer | skip_specs（0） | 17 | D023 |
| V3-T2 语义缓存 | 2026-09-07-v3-semantics-cache | business-engine +1 | 18 | D024 |
| V3-T3 LLM + 失效 | 2026-09-07-v3-llm-provider | business-engine +2 | 19 | D025 |
| V3-T4 前端入口 | 2026-09-07-v3-reasoning-ui | skip_specs（0） | 20 | D026 |
| V3-T5 验收收尾 | 2026-09-07-v3-acceptance | skip_specs（0） | 21 | D027 |
| V4-T1 Watch 领域 | 2026-09-07-v4-watch-domain | business-watch +1 | 22 | D029 |
| V4-T2 委托解析 | 2026-09-07-v4-watch-parser | business-watch +1 | 23 | D029 |
| V4-T3 通用评估 | 2026-09-07-v4-watch-evaluator | business-watch +1 | 24 | D029 |
| V4-T4 Watch UI | 2026-09-07-v4-watch-ui | business-watch +1 | 25 | D029 |
| V4-T5 验收收尾 | 2026-09-07-v4-watch-acceptance | skip_specs（0） | 26 | D029 |
| LLM 兜底阶段 1 | 2026-09-07-llm-refresh-policy | business-engine +1 | 27 | D030 |
| V5-T1 Action 领域 | 2026-09-07-v5-action-domain | business-action +1 | 28 | D031 |
| V5-T2 建档引擎 | 2026-09-07-v5-action-builder | business-action +1 | 29 | D031 |
| V5-T3 状态机 API | 2026-09-07-v5-action-api | business-action +1 | 30 | D031 |
| V5-T4 Action UI | 2026-09-07-v5-action-ui | business-action +1 | 31 | D031 |
| Bug1 前端超时收口 | 2026-09-07-fix-reason-refresh-timeout | skip_specs（0） | 32 | P011 |
| V5-T5 验收收尾 | 2026-09-07-v5-action-acceptance | skip_specs（0） | 33 | D031 |
| P0-1 静态层清理 | 2026-09-07-cleanup-static-layer | skip_specs（0） | 34 | F1–F3/F10 |
| 审计问题收口 | 2026-09-07-fix-audit-f4f9 | skip_specs（0） | 35 | F4–F9/D032 |
| Action 经验沉淀 | 2026-09-08-action-lesson-archive | business-action +1 | 36 | D033 |
| Action 布局修复 | 2026-09-08-fix-action-layout-flex | skip_specs（0） | 37 | — |

## V2 → 能力 → Change 覆盖矩阵
| 能力 | 需求数 | 建立于 | 后续补充自 |
|---|---|---|---|
| business-engine | 15 | C1 基线 | C2(+2)·c3证据(+1)·C3上传(+1)·C5(+1)·V2边界(+3)·**V3-T2(+1)·V3-T3(+2)·LLM兜底1(+1)** |
| business-data-store | 3 | C2 | — |
| data-ingest | 2 | C3 | — |
| upload-mapping | 2 | C4 | — |
| **business-watch** | 4 | V4-T1（2026-09-07-v4-watch-domain） | V4-T2(+1)·V4-T3(+1)·V4-T4(+1) |
| **business-action** | 5 | V5-T1（2026-09-07-v5-action-domain） | V5-T2(+1)·V5-T3(+1)·V5-T4(+1)·经验沉淀(+1) |

## 与外部文档的对应
- 版本/backlog：`docs/版本路线图.md`（V2=迭代 6–16）
- 历史流水：`docs/开发过程记录.md`（迭代 N 一条）
- 经验/决策：`docs/开发问题与经验.md`（P 系列 / D 系列）
- V2 阶段总结：`RELEASE_NOTES_V2.md`
