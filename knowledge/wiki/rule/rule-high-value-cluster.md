# 高客单门店集群规则

版本：3 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：DORA当前项目代码/模拟输入；企业适用性待核对。

证据等级：project_definition

未知项：企业批准阈值/比较基期；实际经营因果

来源：backend/app/engine/engine.py

inputs：Repository门店画像集合，按region分组；不把high_value指标序列当成门店行。

predicate：选择门店数最多的区域（并列按区域名稳定排序），该区域门店数/全表门店数*100>=store_cluster.ratio时形成sig-cluster/o2机会信号。

configuration：store_cluster.ratio缺省60%；其余mix字段也是项目配置，不证明经营因果。

result：仅说明当前代码的信号或因子输出，最终洞察由引擎组装；不代表Action已完成或企业原因已证实。

handling：核对原序列、维度、比较窗口与配置，再从证据和现有Action/Watch流程继续调查，不由本卡更改阈值或判定。

limitations：代码比较规则是项目实现，period文案不代替真实周期类型；企业批准和经营因果未提供。
