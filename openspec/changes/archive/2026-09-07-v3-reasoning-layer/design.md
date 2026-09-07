## Context

见 proposal.md。V3 规划把文本层与判定层解耦（D022）。T1 只搭抽象层与默认 provider，不接线引擎，确保零行为变化、可用测试证明。

## Goals / Non-Goals

**Goals:** 可被 T2/T3 依赖的 provider 协议 + 默认模板实现 + 配置解析 + parity 测试。

**Non-Goals:** 引擎接线、LLM 实现、缓存、API——全部留 T2/T3。

## Decisions

- **Provider 协议**返回 `ReasoningResult`（可含 `semantics`），输入 `ReasoningContext`（引擎给定的触发/因素/数值/snapshot）；模板语义由当前引擎 `_semantics` 提供（**延迟导入**避免包循环）。
- **默认 provider=TemplateProvider**；`resolve_provider()` 读 `DORA_REASONING_PROVIDER`，仅支持 `template`（未知值抛错，防止静默用错 provider）。
- **parity 测试**：对每个引擎洞察，TemplateProvider 输出 semantics == 洞察自带 semantics（由引擎同一函数生成），证明抽象层现阶段零漂移。

## Risks / Trade-offs

- 目前 TemplateProvider 依赖引擎私有 `_semantics`（延迟 import）→ 若未来签名变化会在此暴露；T2 重接时可顺势把语义生成逻辑收编进 reasoning 包。
- 仅支持 template：防止未就绪时误开 LLM。
