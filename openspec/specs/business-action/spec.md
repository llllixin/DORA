# business-action Specification

## Purpose
Dora"行动回路（Action）"能力的行为契约：引擎判定的 problem/opportunity 洞察进入可追溯的 Case 档案（Case→Step→执行→验证→解决/继续→归档），档案与步骤可持久化、可查询、状态迁移有据；判定本身仍由确定性引擎负责，档案回写不改变引擎判定与语义来源（reasonSource）。

## 需求来源表（Traceability）

| 需求 | 由谁新增 | 归档 change | 迭代 |
|---|---|---|---|
| 行动档案与步骤可持久化存取 | V5-T1 Action 领域 | `changes/archive/2026-09-07-v5-action-domain` | 28 |
| 引擎判定的洞察可建档为行动档案（幂等） | V5-T2 建档引擎 | `changes/archive/2026-09-07-v5-action-builder` | 29 |

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
