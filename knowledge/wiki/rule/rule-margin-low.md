# 利润率偏低规则

版本：2 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：DORA当前项目代码/模拟输入；企业适用性待核对。

证据等级：project_definition

未知项：企业批准阈值/比较基期；实际经营因果

来源：backend/app/engine/engine.py

inputs：全国margin序列；margin.target优先取数据库rule_config。

predicate：末尾连续低于target的点数达到3时形成sig-margin/p1问题信号；代码文案称天，输入是否日周期须核对。

configuration：margin.target代码缺省18.5%，数据库配置优先；不是企业已批准阈值。

result：仅说明当前代码的信号或因子输出，最终洞察由引擎组装；不代表Action已完成或企业原因已证实。

handling：核对原序列、维度、比较窗口与配置，再从证据和现有Action/Watch流程继续调查，不由本卡更改阈值或判定。

limitations：代码比较规则是项目实现，period文案不代替真实周期类型；企业批准和经营因果未提供。
