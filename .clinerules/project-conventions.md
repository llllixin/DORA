# Dora 项目开发约定（binding）

## 0. 职责主从（单一事实源，杜绝双源）

| 问什么 | 去哪个文件 | 说明 |
|---|---|---|
| 当前状态 / 现在是第几版 | `docs/版本路线图.md` | 版本状态入口 |
| 已完成版本历史（V1–V5） | `docs/历史版本路线.md` | 归档，不再改动状态 |
| 未解决 / 候选 / backlog | `docs/持续优化路线.md`（每项 = 一个 OpenSpec change id） | **唯一 backlog**；**不在其它文件复制清单** |
| 单个变更怎么做、怎么验收 | `openspec/changes/<id>/`（proposal/spec/design/tasks） | 变更级事实源 |
| 发生过什么（历史） | `docs/开发过程记录.md`（仅"迭代 N"流水，不含待办） | 唯一历史记录 |
| 经验教训 / 决策 | `docs/开发问题与经验.md`（P / D 系列） | 反思落点 |

> 规则：任何"新待办/勾选/状态"只更新路线图；开发记录只追加流水；反思只进 P/D。

## 1. 唯一实现路径（代码改动必须走）

```
持续优化路线 backlog 项（含 OpenSpec change id）
  → /opsx-propose（proposal + specs delta + design + tasks，不写业务代码）
  → 用户 review
  → /opsx-apply（按 tasks 逐条实现，每条勾选必须附可复现验证）
  → /opsx-archive（归档信息必须带【测试证据】+【反思】两节）
  → 同步：路线图勾选该项 + 开发过程记录追加"迭代 N" + 新经验/决策进 P/D
```

- **代码改动（feature 或 bugfix）必须归属某个 change**：若在 in-flight change 内直接做；否则先开一个 change。
- **豁免（可直接提交）**：纯文档/流程/工具链改动（本文档、版本路线图 / 历史版本路线 / 持续优化路线等 docs 规划文件、dev-log 追加、.gitignore、脚手架）——提交信息标注 `docs:` / `chore:` 即代表豁免声明。
- 归档 C1 之类历史步骤如需"补做"，须先在回复里说明理由再执行，不自行脑补用户授权。

## 2. 提交与仓库

- 仓库 git（main），身份本地 `tomara <tomara@mac>`；远端 GitHub `llllixin/DORA`。
- 提交信息中文，如 `feat:` `fix:` `docs:` `chore:` + 一句话 + 摘要体。
- 禁止提交：node_modules、dist、__pycache__、*.tsbuildinfo、vite.config.js/.d.ts、.env、根目录 .DS_Store。

## 3. 动手前

- 改文件前先读目标文件当前内容（可能被格式化改写）；用唯一锚点做小步编辑。
- 沿用现有代码风格（后端 camelCase 契约、frontend features/ 分层）。

## 4. 测试门禁（任务勾"完成"的必要条件）

- 每个任务在其描述里写明验证命令/断言；完成时贴出实际输出。
- 全局回归基线：
  - 后端：`cd backend && python3 -m tests.engine_check`
  - 前端：`cd frontend && npm run build`
  - 端点：curl 相关端点（绕代理环境变量，见速查 P 系列）
  - **一键门禁**：`cd backend && python3 -m tests.run_all`（engine_check + ingest_check + e2e_api_check，需 DB 与后端在线）；change 归档/提交前默认跑一次
- 代码行为改变的任务，勾选前必须补对应断言（把"任务自测"与"spec 场景"对齐，杜绝再次出现 c1 阈值跌破漏测）。
- C5（E2E 四用例）落地后纳入归档前自动 gate。

## 5. 反思门禁（apply/archive 必做）

- 每次 change 归档的提交信息/文档须含：
  - **测试证据**：跑过的命令 + 关键输出/断言
  - **反思**：本次学到什么；若有新坑→P 系列；若有取舍→D 系列（写清退出条件）；若有流程偏差→在本节显式承认
- **propose/design 阶段的关键取舍必须即时记入 D 系列（不等 archive）**：凡是"影响后续复查/学习"的技术选型、范围边界、备选否决，都在 propose 完成时同步写 `docs/开发问题与经验.md`，不得只躺在 design.md 里。
- 汇报前核对事实（任务数、commit、计数），不允许凭记忆报数。

