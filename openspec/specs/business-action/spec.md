# business-action Specification

## Purpose
Dora"行动回路（Action）"能力的行为契约：引擎判定的 problem/opportunity 洞察进入可追溯的 Case 档案（Case→Step→执行→验证→解决/继续→归档），档案与步骤可持久化、可查询、状态迁移有据；判定本身仍由确定性引擎负责，档案回写不改变引擎判定与语义来源（reasonSource）。

## 需求来源表（Traceability）

| 需求 | 由谁新增 | 归档 change | 迭代 |
|---|---|---|---|
| 行动档案与步骤可持久化存取 | V5-T1 Action 领域 | `changes/archive/2026-09-07-v5-action-domain` | 28 |
| 引擎判定的洞察可建档为行动档案（幂等） | V5-T2 建档引擎 | `changes/archive/2026-09-07-v5-action-builder` | 29 |
| 档案步骤可执行推进并验证归档（非法迁移拒绝） | V5-T3 状态机 API | `changes/archive/2026-09-07-v5-action-api` | 30 |
| 档案可在界面真实执行与验证（真数据源） | V5-T4 Action UI | `changes/archive/2026-09-07-v5-action-ui` | 31 |

## Requirements

### Requirement: 行动档案与步骤可持久化存取
系统 SHALL 提供 `action_case` 与 `action_step` 的持久化：一个 case 记录一次行动档案（来源洞察、编号、标题、状态 open|running|waiting_verify|resolved、编排信息与归档文案），其步骤按序号归属该 case，每步有状态 pending|in_progress|done|blocked、note/result 与完成时间。Repository SHALL 支持建案（含首步集）、幂等 seed 迁移、列表、单查（含步骤）、改步骤状态（done 记完成时间）、验证归档（resolved/continue）与删除（级联清步骤、幂等），数据库不可用时与现有接口一致抛"数据源不可用"。

#### Scenario: seed 迁移幂等
- **WHEN** 重复执行 seed（run_seed 两遍）
- **THEN** `action_case` 恰有 5 行（p1/p2/p3/o1/o2，档案编号 PRF-0831/RTN-0816/ORD-1022/UPC-0418/STO-0607），每 case 步骤数稳定（5 行：前 2 done、当前 in_progress、后 2 pending），不翻倍

#### Scenario: 步骤状态与档案 CRUD 往返
- **WHEN** 单查某 case（含 steps）→ 把 seq=3 步骤置 done（带 note/result）→ 再单查 → verify resolved
- **THEN** 步骤状态/note/result/完成时间读回一致；resolved 后 case.status=resolved；删除该 case 后其步骤一并消失（重复删除幂等）

### Requirement: 引擎判定的洞察可建档为行动档案（幂等）
系统 SHALL 提供建档：把引擎判定的 problem/opportunity 洞察转成 action_case（id=insight_id）与步骤集（发现=done、定位/拆解=in_progress、验证=待办、归档=待办；desc/evidence 引用洞察的 trigger/metric/delta 等事实）。建档 SHALL 仅接受"当前引擎判定集内"的 problem/opportunity 洞察：change 洞察、watch escalate 事件与伪造 id 一律拒绝；同洞察重复建档返回既有档案（created=False），不产生第二份。

#### Scenario: 新 problem（如跌破升级 e2）建档成功且幂等
- **WHEN** 注入跌破阈值数据使引擎产出 problem e2 后调用建档
- **THEN** 返回 created=True 的新档案（kind=problem、code 前缀 PRB-、4 步模板、首步 done）；再次建档返回同一档案且 created=False

#### Scenario: 非判定/change/伪造不建档
- **WHEN** 用 change 洞察、watch escalate 假身或引擎判定集之外的 id 调用建档
- **THEN** 抛 ValueError，不写任何行

### Requirement: 档案步骤可执行推进并验证归档（非法迁移拒绝）
系统 SHALL 提供状态机执行入口：步骤仅允许 pending|blocked→in_progress（start）、in_progress→done（带 note/result，全 done 时档案进入 waiting_verify）、in_progress→blocked；档案验证仅允许 resolved（全部步骤 done，note 追加档案）或 continue（回 running）；已 resolved 档案不得再推进。所有非法迁移与对不存在的 case/step 的操作 SHALL 以 4xx 拒绝，不写任何状态。

#### Scenario: 推进到 resolved 的完整链路
- **WHEN** 新档案从 open 经 start/done 推进，末步 done 后档案 waiting_verify，再 verify resolved
- **THEN** 各步状态/note/result 正确，档案终态 resolved，archive 含验证 note；之后任意 start/done/verify 均被拒绝

#### Scenario: blocked 可恢复，resolved 后拒绝
- **WHEN** in_progress 步骤被 block（带 note）后再 start 恢复为 in_progress；已 resolved 档案再次 verify
- **THEN** blocked 可恢复；resolved 档案的再次 verify 被拒绝（4xx）

### Requirement: 档案可在界面真实执行与验证（真数据源）
系统 SHALL 让 Action 页从 /api/action/cases 读取档案列表与详情，并按步骤状态展示推进控件（pending|blocked→开始、in_progress→完成/阻塞、waiting_verify→验证区（归档需填写验证说明 / 继续观察）、resolved→已归档视图）。洞察页的「加入行动回路」SHALL 对当前引擎判定的 problem/opportunity 调用建档接口（幂等返回既有档案），接口拒绝（400）时向用户展示原因且不伪造本地加入；仅当后端不可用时回退本地演示数据并标注。

#### Scenario: 建档入口真实落库
- **WHEN** 在洞察详情点击「加入行动回路」（problem/opportunity，后端在线）
- **THEN** 创建/返回既有档案，页面跳转行动页可见该档案；若该洞察不在当前引擎判定集则显示后端原因而非伪造成功

#### Scenario: 步骤与验证控件真实驱动状态机
- **WHEN** 对档案详情执行「开始/完成/阻塞/归档(带说明)」
- **THEN** 界面调用对应 /api/action/cases 端点并刷新展示最新状态/note/result/归档视图；非法迁移由后端 4xx 拒绝并在界面提示
