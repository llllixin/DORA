## Context

见 proposal.md。T1 已定义 intent 结构雏形（watch_check INTENT 常量）；本 change 让它变成真 parser 输出并保持结构一致（metric_key/dimension/condition{type,days,ref}/frequency/label）。纯文本规则引擎，不触 DB、不触引擎。

## Goals / Non-Goals

**Goals:** 词典化解析 + 显式拒绝 + 建议默认（带标记）+ parse 端点 + watch_check 第 2 节。

**Non-Goals:** 创建/列表 API（T3）；评估器与条件语义最终实现（T3，本 change 只负责**识别与结构化**，不负责判定）；前端接线（T4）；自由语句全覆盖（承认有限，词典+建议 chips 兜底）。

## Decisions

- **指标词典优先匹配**：TARGETS 有序列表（east_orders 在 revenue/orders 前防"华东销售额"误入"销售额"别名），取**最先命中的别名** → metric_key + 默认 dimension。
- **dimension 诚实默认**：只有引擎口径明确的 key 填固定 dim（margin 全国/east_orders 华东/new_sku 全区域/orders|revenue|aov|high_value 全国）；returns 维度是门店级 → dimension=""（整表聚合口径 T3 定义，不在 parser 硬造"全国"）。
- **condition 单语义**：同一句内若既有"连续 N 天下降"又有"跌破 X%"：跌破优先（below/above），streak 降级为建议由 T3 组合？——**决定：单 condition，优先级 breach > streak**，不解析复合条件（T3 再评估是否需要复合）。
- **未识别条件不拒绝、给建议默认**：`condition_defaulted=true` 交确认界面显式展示（D029 显式确认精神：建议可被用户看到并接受/修改）。
- **拒绝诚实**：unknown 指标 ok=false + unsupported（给"支持的关键词示例"），绝不落到"关注任何变化"。
- **频率枚举对齐 Repository**：on_update / daily 09:00 / weekly；未提词 → null（创建时由用户在确认步选择，UI 已有频率 chips）。
- **端点零依赖 DB**：parse 不查库（词典纯代码），离线也可用；返回 HTTP 200 + ok 字段（不是 4xx），客户端看 ok。

## Risks / Trade-offs

- 自由中文语句覆盖率有限 → 建议 chips（6 个，T4 真实映射）与示例句式引导；拒绝路径让用户知道边界，不假装理解。
- 指标别名覆盖不全 → 词典易扩展（TARGETS 常量一个数组）；后续真实需求进来再加别名/新增 key（须同时有引擎支持）。
- 复合条件暂不支持 → 明确拒绝或建议默认；若 T3 评估需要复合（连续下降 **且** 跌破 X%）再扩展 condition schema（加 days+ref 并存），避免过早复杂化。
