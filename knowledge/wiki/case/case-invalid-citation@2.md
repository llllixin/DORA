# 非法引用案例

版本：2 · 状态：reviewed · 来源：simulated

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：DORA当前项目代码/模拟输入；企业适用性待核对。

证据等级：simulated

未知项：本轮独立案例运行结果；企业经营验证材料

来源：openspec/specs/business-agent/spec.md

context：项目工程/演示中的模拟案例，供说明失败边界；不是企业已验证经营样本。

observed_problem：模拟案例：回答 provider 引用本次检索上下文之外的 chunk。后处理必须拒绝发布答案并记录 citation_not_in_context，不能仅检查引用格式。

handling：按本模拟案例正文与来源约束处理：模拟案例：回答 provider 引用本次检索上下文之外的 chunk。后处理必须拒绝发布答案并记录 citation_not_in_context，不能仅检查引用格式。

verification：核对来源 openspec/specs/business-agent/spec.md 的代码/契约；有相应回归时在隔离环境复现。本卡说明模拟机制；版本发布回归证据另见A02验收记录，不代表企业验证。

result：记录上述机制与预期处理，不填本轮未取得的实测结果，也不宣称企业经营收益。

reuse_scope：只在同项目/来源条件和对应接口边界下参考；其他输入、环境与企业流程需另外核验。

limitations：source_type保持simulated；测试通过也不能升级为verified_case。
