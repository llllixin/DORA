# 利润率定义与边界

版本：3 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：当前DORA项目代码/演示数据；企业应用须核对实际定义。

证据等级：project_definition

未知项：企业分子分母；输入采集方法

来源：knowledge/ontology/releases/dora-ontology-v2.json；backend/app/engine/engine.py；backend/app/rag/service.py

definition：项目利润率是 margin 输入序列；项目未声明企业财务分子与分母，不等同已确认毛利率或净利率。

physical_binding：metric.margin → query_metric 的 margin/全国，原单位为%。当前RAG只返回工具提示，不执行读取。

calculation_boundary：compute_snapshot读取全国序列末值，不从营收重新计算利润率；不得自行补算企业财务公式。

comparison_scope：同主体、时间范围、单位和已确认口径方可比较；全国范围不替代其他区域。

usage：用于解释利润率规则输入和指向业务读取入口；实时数值由业务读取，不写入本卡。

limitations：毛利率/净利率先澄清；企业公式、收入确认与采集方法未提供。
