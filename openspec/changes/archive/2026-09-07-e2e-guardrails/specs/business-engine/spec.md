## ADDED Requirements

### Requirement: 跌破阈值自动升级为问题
当华东订单量跌幅跌破配置阈值（默认 -3.0%）时，系统 SHALL 自动生成 type=problem 的洞察 `e2`（如"华东订单量跌破升级阈值"），并将其 metric/delta/semantics 指向对应数据；不再把该情形作为"待升级 change"输出。

#### Scenario: 跌破阈值生成 e2 问题
- **WHEN** 华东订单序列跌幅 ≤ 阈值（如上传跌破 -3% 的数据）
- **THEN** `/api/insights?type=problem` 包含 id=`e2`，且 `/api/insights?type=change` 不再包含对应 c1 变化

#### Scenario: 未跌破仍为变化观察
- **WHEN** 华东订单跌幅介于 -1% 与阈值之间
- **THEN** 保持 change（c1）输出，不生成 e2
