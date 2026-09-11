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
| 已归档档案可沉淀为经验库并展示处理过程 | 迭代36 经验沉淀 | `changes/archive/2026-09-08-action-lesson-archive` | 36 |
| 归档与经验按类型写入统一知识库并可筛选 | 迭代38 知识库 | `changes/archive/2026-09-08-knowledge-archive` | 38 |
| 归档知识随档案生命周期一致（删除级联+原子入库+无孤儿） | Phase0 生命周期收口 | `changes/archive/2026-09-09-knowledge-lifecycle` | 40 |
| 行动步骤可指定负责专家团（per-step 持久化） | 迭代44 行动回路页收口 | `changes/archive/2026-09-11-action-loop-timeline` | 44 |

## Requirements

### Requirement: 行动档案与步骤可持久化存取
系统 SHALL 提供 `action_case` 与 `action_step` 的持久化：一个 case 记录一次行动档案（来源洞察、编号、标题、状态 open|running|waiting_verify|resolved、编排信息与归档文案），其步骤按序号归属该 case，每步有状态 pending|in_progress|done|blocked、note/result 与完成时间，并承载**负责专家名单**（`experts`，字符串列表，缺省空列表——表示尚未指定负责专家）。Repository SHALL 支持建案（含首步集）、幂等 seed 迁移、列表、单查（含步骤）、改步骤状态（done 记完成时间）、设置步骤负责专家名单、验证归档（resolved/continue）与删除（级联清步骤、幂等），数据库不可用时与现有接口一致抛"数据源不可用"。

#### Scenario: seed 迁移幂等
- **WHEN** 重复执行 seed（run_seed 两遍）
- **THEN** `action_case` 恰有 5 行（p1/p2/p3/o1/o2，档案编号 PRF-0831/RTN-0816/ORD-1022/UPC-0418/STO-0607），每 case 步骤数稳定（5 行：前 2 done、当前 in_progress、后 2 pending），不翻倍

#### Scenario: 步骤状态与档案 CRUD 往返
- **WHEN** 单查某 case（含 steps）→ 把 seq=3 步骤置 done（带 note/result）→ 再单查 → verify resolved
- **THEN** 步骤状态/note/result/完成时间读回一致；resolved 后 case.status=resolved；删除该 case 后其步骤一并消失（重复删除幂等）

#### Scenario: 迁移前的历史步骤行缺省为空专家名单
- **WHEN** 读取迁移前已存在的步骤行（未显式设置过负责专家）
- **THEN** 该步 `experts` 返回空列表（不报错、不伪造专家），界面按"未指定负责专家"呈现

### Requirement: 行动步骤可指定负责专家团（per-step 持久化）

系统 SHALL 支持为**单个行动步骤**指定负责专家：`action_step` 持久化该步的负责专家名单（`experts`，字符串列表，缺省空列表），并通过 `POST /api/action/cases/{case_id}/steps/{seq}/experts` 提供**整体设置**入口（幂等：请求体为完整名单，重放同值不改变结果）。写入 SHALL 做结构性校验：名单元素为非空字符串、同名校验去重、数量上限 8；超限、空名或名单非列表 SHALL 以 4xx 拒绝且不写库。已 `resolved` 的档案 SHALL 冻结该操作（4xx，与既有步骤推进冻结一致）；不存在的 case/step SHALL 返回 404。返回体 SHALL 与既有步骤动作端点同形（`{ok, case}`，case 含最新 steps），使调用方一次拿到权威状态。档案级 `orchestration.experts` 保留「系统建议」语义，不因本需求改变。

#### Scenario: 设置负责专家并读回一致（幂等）
- **WHEN** 对某档案 seq=1 步骤 POST 名单 `["经营分析专家","财务专家"]`，随后单查该档案，再重放同一请求
- **THEN** 单查返回该步 `experts` 与设置值同名同序；重放返回 200 且名单不变（不重复、不追加）

#### Scenario: 去重与上限
- **WHEN** 提交含重复项的名单（`["财务专家","财务专家"]`）或含 9 个不同专家的名单，或含空字符串的名单
- **THEN** 重复项被去重为单条；超过 8 个或含空名的请求被 4xx 拒绝且库中名单保持原值

#### Scenario: resolved 档案冻结专家设置
- **WHEN** 对 status=resolved 的档案设置步骤负责专家
- **THEN** 返回 4xx，该步 `experts` 不变

#### Scenario: 不存在的步骤被拒绝
- **WHEN** 对不存在的 case 或不存在的 seq 设置负责专家
- **THEN** 返回 404（case）或 4xx（seq），不新增任何行

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

界面 SHALL 遵循三条呈现规则：① **档案列表按洞察列表形态呈现**——每行显示档案类型标签、标题、来源与状态标记；状态标记 SHALL 为**展示层二值映射**（open|running|waiting_verify → 「执行中」，resolved → 「已归档」），并 SHALL NOT 改变内部状态、状态机迁移或详情页的细粒度状态展示；列表 SHALL 将「执行中」排在前、「已归档」排在后并显示两类计数。② **机会/问题板块的步骤 SHALL 呈现为时间线**：每步可展开/收起（默认展开当前进行中的步骤），折叠态至少可读状态与标题，展开态展示描述、归因（why）、备注与结果；推进控件 SHALL 位于步骤行右侧，与展开控件同区。③ **每步 SHALL 可指定负责专家与定位数据**：步骤行内展示该步负责专家名单（空时呈现"未指定"），可选择专家添加/移除并调用后端接口落库（失败时提示原因且不伪造本地状态）；每步 SHALL 提供数据定位入口，展示该步引擎给定的定位说明（evidence）并可打开该档案的证据链，SHALL NOT 新造数据源或凭空生成定位。

#### Scenario: 建档入口真实落库
- **WHEN** 在洞察详情点击「加入行动回路」（problem/opportunity，后端在线）
- **THEN** 创建/返回既有档案，页面跳转行动页可见该档案；若该洞察不在当前引擎判定集则显示后端原因而非伪造成功

#### Scenario: 步骤与验证控件真实驱动状态机
- **WHEN** 对档案详情执行「开始/完成/阻塞/归档(带说明)」
- **THEN** 界面调用对应 /api/action/cases 端点并刷新展示最新状态/note/result/归档视图；非法迁移由后端 4xx 拒绝并在界面提示

#### Scenario: 列表状态为执行中/已归档二值映射
- **WHEN** 档案列表同时存在 status=open / running / waiting_verify / resolved 的档案
- **THEN** 列表行状态标记分别为 执行中/执行中/执行中/已归档，且「执行中」行排在前；打开 resolved 档案详情仍显示「已归档」而内部状态值与接口返回不变

#### Scenario: 步骤时间线可展开收起且控件在右侧
- **WHEN** 打开一个含多步的档案详情
- **THEN** 步骤按时间线纵向呈现，当前进行中的步骤默认展开、其余折叠；每步行右侧同时可见该步可用的推进控件与展开/收起控件，点击切换该步展开态且不影响其它步骤状态

#### Scenario: 每步可添加负责专家并落库
- **WHEN** 在某步的专家区选择一个专家并添加（后端在线）
- **THEN** 界面调用步骤专家接口，刷新后该步显示新专家名单；后端拒绝（4xx）时界面提示原因且不显示未落库的专家

#### Scenario: 每步可定位数据
- **WHEN** 在某步点击「定位数据」/证据定位入口
- **THEN** 打开该档案的证据链，且该步展示其引擎给定的定位说明（evidence）；无 evidence 的步骤呈现"暂无定位说明"而非编造

### Requirement: 已归档档案可沉淀为经验库并展示处理过程
系统 SHALL 提供"沉淀经验"：对 status=resolved 的行动档案调用归档接口后，将 `case_lesson` 记录（case 编号/类型/标题/处理过程 archive/结论 note/时间）写入经验库；同一档案重复沉淀幂等（返回既有）；非 resolved 档案调用 SHALL 被拒绝（4xx）。经验的**查看入口 SHALL 收敛到知识库**（统一知识库的 lesson 类目，按时间倒序），Action 页 SHALL NOT 再重复承载经验列表；沉淀成功后的界面提示 SHALL 指向知识库。知识库条目的处理过程 SHALL 可展开/收起查看，SHALL NOT 使用无实际展开行为的占位按钮冒充可交互。

#### Scenario: resolved 后沉淀经验且幂等
- **WHEN** 档案已 resolved，先 POST archive-as-lesson 再重复 POST
- **THEN** 首次写入经验库（created=True），重复调用返回既有且经验条数不变

#### Scenario: 未完成档案拒绝沉淀
- **WHEN** 对 running/waiting_verify 档案调用 archive-as-lesson
- **THEN** 返回 4xx 且经验库无新增

#### Scenario: 经验只在知识库可见且处理过程可展开
- **WHEN** 沉淀某 resolved 档案的经验后查看 Action 页与知识库页（筛选「经验」）
- **THEN** Action 页不再出现经验列表块；知识库「经验」类目出现该条（含处理过程与结论），处理过程默认收起、点击后展开可见全文

### Requirement: 归档与经验按类型写入统一知识库并可筛选
系统 SHALL 提供 `knowledge_archive`：当行动档案 verify resolved 时按类型（problem|opportunity，取自档案 kind）自动写入一条含完整处理过程（archive）的知识；当档案沉淀经验（case_lesson）时按类型 lesson 再写入一条（含处理过程与结论）。同类型同来源幂等（(entry_type, source_id) 唯一）。系统 SHALL 提供知识库查询：可按类型筛选并返回各类型计数；类型 change 为预留（无来源时不产生数据）。

#### Scenario: resolved 与沉淀经验自动按类型入库
- **WHEN** 档案 verify resolved，随后对该档案沉淀经验
- **THEN** knowledge_archive 出现两条：problem（content=处理过程）与 lesson（content=处理过程、note=结论）；重复动作不新增（幂等）

#### Scenario: 按类型筛选与统计
- **WHEN** GET /api/knowledge?type=problem
- **THEN** 只返回 problem 类条目且 stats 反映各类型计数

### Requirement: 归档知识随档案生命周期一致（删除级联 + resolved 入库原子 + 无孤儿不变式）

系统 SHALL 保证 `action_case`、`case_lesson`、`knowledge_archive` 三表生命周期一致：

1. 当行动档案被删除（单删或全清）时，同一数据库事务内 SHALL 级联删除其全部 `action_step`、`case_lesson` 与 `knowledge_archive`（source_id=该档案 id）行，不残留孤儿；重复删除幂等返回 False。
2. 行动档案 verify resolved（含 note 追加 archive）与其知识自动入库（按 case.kind 写 problem|opportunity 行）SHALL 在同一数据库事务内完成——不允许出现"档案已 resolved 但知识行缺失"的中间态；知识写入按 (entry_type, source_id) 幂等。
3. 任何 status ≠ resolved 或不存在的档案不得存在其 `case_lesson` / `knowledge_archive` 行（不变式）；测试门禁 SHALL 在运行前自愈清理脏库中的此类孤儿并在结束后断言该不变式成立。

#### Scenario: 删除档案级联清理经验与知识
- **WHEN** 一个已 resolved 且已沉淀经验（存在 case_lesson 与 problem/opportunity + lesson 知识行）的档案被 delete_action_case
- **THEN** 该档案的 action_step、case_lesson 与全部 knowledge_archive 行在同事务内一并消失；再次删除返回 False（幂等）

#### Scenario: resolved 入库原子且幂等
- **WHEN** 对全 done 档案 flow.verify outcome=resolved（带 note），随后重复 verify 被拒绝、再 create_case_lesson 两次
- **THEN** verify 返回时该档案已 resolved 且对应知识行（含处理过程 archive 与 note）在同一事务内已存在；重复 verify 4xx；重复沉淀 lesson created=False 且不新增行

#### Scenario: 非 resolved 档案无孤儿行（不变式）
- **WHEN** 遍历全部 action_case 并核对 case_lesson / knowledge_archive
- **THEN** 不存在 status=running/waiting_verify/open 的档案仍带有 lesson 或 knowledge 行；运行前发现的脏行被自愈清理
