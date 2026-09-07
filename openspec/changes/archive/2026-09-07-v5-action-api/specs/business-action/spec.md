## ADDED Requirements

### Requirement: 档案步骤可执行推进并验证归档（非法迁移拒绝）
系统 SHALL 提供状态机执行入口：步骤仅允许 pending|blocked→in_progress（start）、in_progress→done（带 note/result，全 done 时档案进入 waiting_verify）、in_progress→blocked；档案验证仅允许 resolved（全部步骤 done，note 追加档案）或 continue（回 running）；已 resolved 档案不得再推进。所有非法迁移与对不存在的 case/step 的操作 SHALL 以 4xx 拒绝，不写任何状态。

#### Scenario: 推进到 resolved 的完整链路
- **WHEN** 新档案从 open 经 start/done 推进，末步 done 后档案 waiting_verify，再 verify resolved
- **THEN** 各步状态/note/result 正确，档案终态 resolved，archive 含验证 note；之后任意 start/done/verify 均被拒绝

#### Scenario: blocked 可恢复，resolved 后拒绝
- **WHEN** in_progress 步骤被 block（带 note）后再 start 恢复为 in_progress；已 resolved 档案再次 verify
- **THEN** blocked 可恢复；resolved 档案的再次 verify 被拒绝（4xx）
