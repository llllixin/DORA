## Context

见 proposal.md。T1-T4 的自动断言已分散在 reasoning_check；T5 收敛为"金样本 + 清单"。

## Goals / Non-Goals

**Goals:** 可复现的模板金样本回归；把"LLM 不改数字"红线纳入门禁表述；产出人工验收清单。

**Non-Goals:** 不改产品代码；不做真实 LLM 在线验证（无 key 环境保持 template 模式全绿）。

## Decisions

- **金样本**：以 `python -m app.seed`（出厂重置）后 `run_engine()` 的模板输出为基线落盘 JSON（排除纯展示字段），golden_check 每次比对（确定性）。
- 红线断言复用/归拢：reasoning_check 已含数值稳定单元与集成断言；验收清单显式引用其命令。
- 文档：`V3_ACCEPTANCE_CHECKLIST.md` = §3A.4 可勾选清单（自动项给命令，人工项给核对标准）。

## Risks / Trade-offs

- 基线会随引擎语义演进失效 → 需显式"重生成基线"流程（清单注明，改判定语义时重跑 `python3 -m tests.golden_check --write` 并走变更评审）。
- 清单新增文档需人工跟进 → 作为 V3 收尾的 sign-off 载体。
