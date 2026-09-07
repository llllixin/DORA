## ADDED Requirements

### Requirement: 新品销量洞察的证据对齐
「新品销量快速增长」洞察（id=`c3`）的证据链 SHALL 展示与洞察主题一致的**新品销量原始行**（周标签 + 销量 + 增量），不得再使用其它指标（如利润率）的占位行。

#### Scenario: c3 证据链为新品销量数据
- **WHEN** 请求 `GET /api/evidence/c3`
- **THEN** 返回的 rawRows 首行包含「新品销量」且数据来自新品周销量源数据

#### Scenario: 自检防回归
- **WHEN** 运行引擎自检 `python3 -m tests.engine_check`
- **THEN** 断言 c3 的 evidence kind 为 `new_sku`（非 `margin`）且证据行含新品销量数据
