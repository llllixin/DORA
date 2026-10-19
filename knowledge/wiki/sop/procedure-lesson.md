# 经验沉淀流程

版本：2 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：当前DORA项目代码/演示数据；企业应用须核对实际定义。

证据等级：project_definition

未知项：真实经营结果验证；不可变历史数据快照

来源：backend/app/routers.py；backend/app/repository.py；openspec/specs/business-action/spec.md

preconditions：来源行动档案为resolved；archive-as-lesson请求提供非空note；resolved仅表示流程结束。

steps：读取已归档档案→创建case_lesson→在同事务写lesson知识归档→治理适配生成draft候选→人工检查来源、适用范围及正文→审核后显式发布新版本。

result：原知识库保留处理记录展示；正式Wiki案例另经审核与版本发布。重复沉淀和重复候选生成均按来源身份幂等。

failure_handling：档案未resolved或结论为空按现有接口拒绝；候选写入失败需同事务回滚。正文变化后重新审核；来源失效不能继续发布。

limitations：候选/审核/发布由A02治理模块提供，本机CLI显式执行；无企业历史快照时仅可发布标明reported的处理记录，不升级verified_case。
