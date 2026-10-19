# 华东订单阈值规则

版本：3 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：当前DORA项目代码/演示数据；企业应用须核对实际定义。

证据等级：project_definition

未知项：企业批准阈值；实际同比/环比基期

来源：backend/app/engine/engine.py；backend/app/series_order.py；knowledge/ontology/releases/dora-ontology-v2.json

inputs：east_orders/华东的按周期排序序列；缺华东数据没有可用delta，不用全国或演示值补齐。

predicate：引擎以末值相对前两个可用值均值计算delta_pct；delta_pct < -1.0时进入下降分支，且delta_pct <= east.threshold时形成问题，否则形成观察变化。

configuration：east.threshold优先取rule_config，缺省为代码默认-3.0；这个值是项目默认配置，不是企业统一标准。

result：达到升级分支产生sig-east-breach/e2问题信号；未达到升级分支产生观察变化。引擎信号不等于某个Watch已完成移交。

handling：核对来源、期间和阈值配置，依现有Watch/Action接口继续处理；不由Wiki改写判定。

limitations：变化比较窗口是当前实现，不把它称作环比或同比；阈值和因果需业务确认。
