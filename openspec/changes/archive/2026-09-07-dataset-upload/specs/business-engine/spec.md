## ADDED Requirements

### Requirement: 数据更新后引擎端点即时反映
当数据集通过上传/样例接口完成写入后，引擎端点（`/api/pulse`、`/api/insights*`、`/api/evidence/*`）SHALL 在不重启服务的情况下按请求读取最新 Repository 数据并反映变化。

#### Scenario: 上传新数据改变脉搏结果
- **WHEN** 上传一组与当前种子数值不同的合法数据后调用 `/api/pulse` 或 `/api/insights`
- **THEN** 结果中的相关指标/触发条件体现新数据（与上传前不同）
