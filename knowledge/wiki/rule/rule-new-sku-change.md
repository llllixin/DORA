# 新品销量变化规则

版本：2 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：DORA当前项目代码/模拟输入；企业适用性待核对。

证据等级：project_definition

未知项：企业批准阈值/比较基期；实际经营因果

来源：backend/app/engine/engine.py

inputs：全区域new_sku新品销量序列，不是新品SKU种数。

predicate：末值相对首个可用点的delta_pct有效且>=30时生成sig-new-sku/c3变化信号；尚未证明增长可复制。

configuration：30%为代码比较值；可用序列首末不是已确认企业新品窗口。

result：仅说明当前代码的信号或因子输出，最终洞察由引擎组装；不代表Action已完成或企业原因已证实。

handling：核对原序列、维度、比较窗口与配置，再从证据和现有Action/Watch流程继续调查，不由本卡更改阈值或判定。

limitations：代码比较规则是项目实现，period文案不代替真实周期类型；企业批准和经营因果未提供。
