## Context

见 proposal.md。watch_check 第 3 节已在 Repository 层证明 escalate 引用引擎 e2；第 4 节用 HTTP + 文件上传把"用户委托→数据恶化→升级回脉搏"整条真实链路固化为门禁。

## Goals / Non-Goals

**Goals:** watch_check 第 4 节 HTTP E2E（Case 3 change + Case 4 escalate）；V4 验收清单；run_all 保持 6 段 ALL GREEN。

**Non-Goals:** 新 spec 需求；Action 闭环（V5）；新 UI 功能；Golden 基线变化（9 insights 不变）。

## Decisions

- **E2E 走 HTTP 而非直调 Repository**：Case 3/4 本质是"委托 + 数据更新"真实链路，HTTP 才能覆盖 upload 后即时评估与 REST 卡片状态；复用 e2e_api_check 的 no-proxy helper（watch_check 与 e2e 同属 run_all，后端在线前置一致）。
- **断言最小且稳定**：不断言事件总数（seed 数据决定首次是否命中），只断言"存在 escalate 事件且 engine_insight==e2"与 Case 3 change 事件存在性、上传后引擎 insights 出现 e2。
- **验收清单结构沿用 V3**（A 自动/B 边界/C 人工/D 收尾 + Sign-off）：V4 全部自动项给命令，C 段留给用户在界面确认后填 sign-off。
- skip_specs：本 change 不改任何系统行为要求（需求在 T3/T4 已入 spec），仅固化测试与文档。

## Risks / Trade-offs

- watch_check 从"DB-only"变为"需后端" → run_all 本就需要后端（e2e_api_check），无新增前置负担；单独跑 watch_check 的文档注明需后端与 DB。
- HTTP E2E 对 seed 数据形状敏感 → 每次 sample 出厂 + 断言"存在性"而非"总数/具体值"，降低脆弱性。
