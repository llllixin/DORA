## Context

见 proposal.md。归档语义=确定性记录；knowledge_archive 统一入口承接两类写入（resolved 自动 + 沉淀经验）。

## Goals / Non-Goals

**Goals:** 表/写入钩子/查询/stats；前端知识库页（chips 筛选+卡片）。

**Non-Goals:** 人工编辑/删除入口（测试自清用 repo）；change 类来源（预留，Watch/变化升级→知识 留后续）；全文检索。

## Decisions

- **entry_type 与 case.kind 对齐**（problem|opportunity）；lesson 单独类型；change 仅枚举预留。
- **幂等键** (entry_type, source_id)：resolved 只会触发一次（resolved 冻结），lesson case_id 幂等已有。
- **写入点选在语义发生处**：resolved 由 flow.verify 写（不放在 repo.verify 以免层污染）；lesson 在 create_case_lesson 同事务补写。
- **content=处理过程（archive 全文），note=结论（resolved 的验证 note / lesson resolution）**——保证"看过程 + 看结论"。
- 前端独立 Page 'knowledge'，导航「◈ 知识库」；chips 计数来自后端 stats。

## Risks / Trade-offs

- 知识与 lesson 存在双表语义（case_lesson 为"经验库"、knowledge_archive 为"全归档库"）→ 文档注明：knowledge=统一归档视图，lesson=经验引用视图；未来如冗余可合并（留 D 记录）。
- resolved 自动入库会让知识在用户"沉淀经验"前就有 problem 行——符合"归档即入库"需求（用户选项 A）。
