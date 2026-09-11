## ADDED Requirements

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

## MODIFIED Requirements

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
