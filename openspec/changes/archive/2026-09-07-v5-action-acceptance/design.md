## Context

见 proposal.md。action_check 第 1–3 节已覆盖领域/建档/状态机（DB/服务层）；第 4 节走 HTTP 把"真实链路"（上传→引擎升级→建档→执行→归档 / 机会 continue）固化为门禁。

## Goals / Non-Goals

**Goals:** action_check 第 4 节 HTTP E2E；V5 验收清单；版本速览 V5 → 已实现待人工验收。

**Non-Goals:** 新 spec/需求/UI；删除旧 /actions 静态端点（保留至 V5 sign-off 后如需再清，避免破坏 e2e Case1/2 历史断言）；Golden 变化。

## Decisions

- **复用 watch 升级链路做建档源**：watch→escalate 不自动建档（红线），但引擎据此产出 problem e2 → 允许建档——这正是 Case 4"升级→问题→Action"的路径。
- **断言"存在性+终态"**：不断言每次中间步骤 HTTP 细节（第 3 节已覆盖服务层），只固化端到端事实：created True、e2 resolved、archive 含验证 note、o1 continue→running。
- **清理策略**：sample 不重置 action 档案（seed 只 upsert 5 例）→ 测试自清 e2 + 结束后 sample 还原数据。

## Risks / Trade-offs

- 依赖后端在线（run_all 前置已具备）；断言存在性降低对数据形状敏感度。
