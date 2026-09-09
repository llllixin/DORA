# Dora · V2 Release Notes（阶段总结）

> 发布日期：2026-09-07 ｜ 分支基线：`main`
> 一句话：把 v9 单文件 Demo 演进为 **React + FastAPI + PostgreSQL 的 AI 主动经营系统（V2）**，已完成"真实引擎 + 持久化 + 数据入口 + 映射 + 质量门禁"，判断语义全部收归后端。
> 快照说明：本文是 V2 sign-off 的阶段总结（2026-09-07），**冻结不再更新**；后续版本/backlog 状态以 `docs/版本路线图.md` 与 `docs/持续优化路线.md` 为准（文档职责分层见 `docs/文档地图.md`）。

---

## 1. 阶段总结：我们从哪来、到哪去

### 起点与目标
- 基线是 v9 单文件 HTML Demo；目标是升级为可运行、可演进、可接真实业务数据与 AI Agent 的全栈产品（docs/完整详细的搭建说明流程.md 路线）。

### 版本里程碑
| 版本 | 范围 | 迭代 | 状态 |
|---|---|---|---|
| V1 | React+TS+Vite 四大页面、证据链、hash 导航、localStorage、**冷启动数据入口**、Mock→HTTP 服务层 | 0–5 | ✅ |
| V2 | **确定性业务引擎**（Metric→Rule→Signal→Insight）接入主端点、PostgreSQL Repository、真实上传/映射入库、E2E 门禁、边界修复 | 6–16 | ✅ |
| V3/V4/V5 | LLM 解释 / Watch 真实委托调度 / Action 真闭环 | — | ⬜ 见 §6 |

### V2 交付清单（对应 OpenSpec 归档 change）
- **C1 `extend-engine-coverage`**：c2 数据事件、o2 门店集群机会进引擎覆盖（消除静态兜底）
- **C2 `postgres-repository`**：SQLAlchemy 四表 + Docker PG16 + 幂等 seed + 规则配置化（DB 离线 503）
- **C3 `dataset-upload`**：csv/xlsx 规范格式上传事务落库、样例出厂重置、冷启动入口接通真实后端
- **C4 `upload-mapping`**：上传"列→口径"映射（预览 + mapping 入库）
- **C5 `e2e-guardrails`**：4 个核心验收用例 E2E + 跌破阈值自动升级 e2 + `tests/run_all`
- 修复与清理：`fix-new-sku-evidence`（c3 证据错配）、`code-cleanup`（死代码/阈值单源/证据 DB 化）、`fix-v2-critical-boundaries`（空数据门禁/阈值语义/时间动态化/名称下沉）

### 架构现状
```text
React Frontend :5173（Pulse/Insight/Action/Watch + 冷启动 + 更新数据）
        │  /api 代理
FastAPI :8000 ── Pulse/Insights/Evidence/Action/Watch/Datasets/Engine
        │
Repository(SQLAlchemy) ── PostgreSQL:16（Docker，dora@5432）
        │
Engine（纯确定性）：compute_snapshot(repo, rules)
  → evaluate_signals(_below/_breach 规则函数)
  → build_insights（模板文案 + semantics + confidence）
  → engine_evidence（原始行由 Repository 生成）
        │
输入源：规范格式直传 / 任意列布局映射 / 样例出厂重置（rule_config 阈值可调）
```

### 质量门禁（提交/归档前跑）
```bash
cd backend && python3 -m tests.run_all   # engine_check + ingest_check + e2e_api_check（4 用例）
cd frontend && npm run build
# 端点冒烟：python3 /tmp/dora_smoke.py（5173 代理、绕本地代理环境变量）
```
最近一次：**run_all ALL GREEN ✅**

---

## 2. 已知边界与范围脚注（重要）

> **⚠️ V2 版本的 Watch/Action 域为静态演示数据**：引擎可计算并自动升级 e2，但"业务目标委托、行动 case 自动建档与真实执行"仍为演示/静态，**真实动态委托功能将于 V4 版本上线**。V2 页面"持续关注"计数旁有 `?` 悬浮提示标识静态性。

其他已知边界：
- 图表配置为前端展示层（静态 Demo），未随引擎数值数据化。
- 叙事文案为引擎模板占位，V3（LLM 解释）将替换文本层。
- 证据时间戳取最近更新事件（事件仅存 HH:MM，日期取当天）。
- 上传/映射为单值列契约（组合口径、自动推断不在 V2 范围）。

---

## 3. 工程与流程基建（可追溯性）
- **OpenSpec spec-driven**：每个里程碑/修复 = 一个 change（propose → apply → archive），完整归档位于 `openspec/changes/archive/`（proposal/specs/design/tasks 全保留）。
- **正式能力 spec**：`openspec/specs/` 下的 business-engine / business-data-store / data-ingest / upload-mapping。
- **单一事实源**：版本/backlog=docs/版本路线图.md；历史流水=docs/开发过程记录.md；经验决策=docs/开发问题与经验.md（P 系列 + D 系列 001–021）。
- **关键决策速览（D）**：D009 稳定前不引 Agent、D014 引擎先行/模板占位、D016 PG Repository、D017 上传格式契约、D018 映射单值列、D019 run_all 门禁、D021 V2 边界修复单 change。

---

## 4. 下一步（进入条件）
- **V3（LLM 解释层）**：在 PG 上的 Metric→Rule→Signal→Insight 稳定后，用 LLM 替换叙事模板（只解释，不改判定）。
- **V4（Watch 真实委托）**：业务目标委托、规则调度、跌破自动升级/升级路径真正落地（V2 脚注的退出条件）。
- **V5（Action 真闭环）**：action_case/action_step 状态化、执行与回写。

---

## 5. 文档索引
| 需求 | 文件 |
|---|---|
| 完整搭建路线 | docs/完整详细的搭建说明流程.md |
| 版本/backlog | docs/版本路线图.md |
| 迭代历史 | docs/开发过程记录.md |
| 问题/决策/经验 | docs/开发问题与经验.md |
| 架构 | docs/architecture.md |
| 本文件 | RELEASE_NOTES_V2.md（V2 阶段总结） |

