# 高客单门店占比与集合边界

版本：3 · 状态：reviewed · 来源：project

审核：project-user:A02-review-2026-10-14 · 用户“开始实施”批准A02设计与44卡片；项目来源审核，非企业成效验证

适用范围：DORA当前项目代码/模拟输入；企业适用性待核对。

证据等级：project_definition

未知项：企业采集/计算规范；企业时间窗口与可比口径

来源：backend/app/models.py

definition：项目high_value表示全国高客单门店占比，单位%；不是大额订单占比，也不是门店集合。

physical_binding：metricKey=high_value；默认dimension=全国；dimensionPolicy=fixed；sourceUnit=% 当前RAG提示不等于执行。

calculation_boundary：项目实际读取以来源代码与A01本体为准；输入来源的采集/企业分子分母未提供，不以通用定义填补。

comparison_scope：同主体、时间窗口、单位与口径方可比较；明确不支持范围时澄清，不用默认维度覆盖。

usage：解释该概念和读取边界；具体当前值及变化必须读业务数据/引擎，不从Wiki取实时数值。

limitations：本卡为项目实现说明；企业财务/采集规范和跨期可比性需确认，源定义不证明经营因果。
