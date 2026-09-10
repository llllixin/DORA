# Dora · 类 Dify Agent 工作流设计（可验证 Agent Flow）

> 定位：把「前端页面期望 Dora 做的事」翻译成 **Dify 可落地的节点图 + 多 Agent 编排 + RAG + 工具契约 + 验证断言**。
> 用途：在 Dify 里搭建一条**可验证的 agent 流**（能跑、能断言、能回放），并映射回本项目的页面与后端。
> 性质：设计稿（不承载 backlog 状态）。候选/排期见 `docs/持续优化路线.md`；文档职责见 `docs/文档地图.md`。
> 依据：搭建文档 #19–#26（Agent 思维链 / Tool Calling / Evidence First / Confidence / 后台流程）、#36（4 个核心 E2E 用例）、本仓 6 个能力 spec、31 个 REST 端点、前端 5 个页面契约。

## 0. 一句话架构

```text
确定性判定层（可信）  ←  Metric → Rule → Signal → Insight → Evidence
        ↓  只读工具
Agent 编排层（会商）   ←  Supervisor + 角色 Agent（专家团）+ RAG 记忆
        ↓  结构化产出
行动工作流层（可控）   ←  Case → Step → 验证 → 归档 → 经验沉淀
        ↓
RAG 记忆层（可复用）   ←  knowledge_archive / case_lesson → 检索 → 引用
```

三条红线（贯穿所有节点）：
1. **判定不由 LLM 产生**：problem/opportunity/change 身份只来自引擎；Agent 只能引用。
2. **数字不由 LLM 产生**：任何数值必须来自工具/引擎 payload；LLM 输出数字要做「数值锁」断言。
3. **置信度不由 prompt 生成**：由 Confidence Aggregator 计算（数据完整性/趋势稳定性/归因强度/证据覆盖/规则命中）。

---

## 1. 前端页面 → 期望的 Agent 行为（页面即验收面）

| 页面 | 用户动作 | 期望 Agent 流 | 页面上的验收点 |
|---|---|---|---|
| 冷启动 / 更新数据 | 上传 xlsx / 载入样例 | ingest → normalize → engine → pulse 就绪 | 顶栏数据标签更新、Pulse 计数刷新 |
| 业务脉搏 Pulse | 看总览 / 点「让 Dora 帮我跟进」 | 读 `/pulse`+`/insights`+`/watch`；跟进=真实建 Watch 委托 | 优先级卡文案=引擎字段；监控卡=真实委托；跟进后 Watch 列表出现 |
| 洞察 Insight | 看归因 / 点「问 Dora」/「生成行动」 | 解释（semantics）→ 追问（RAG+证据）→ 生成 Action | 归因 chips、置信、证据链可打开、行动档案生成 |
| 行动回路 Action | 推进步骤 / 填写验证 / 归档 | 建档 → 步骤执行 → 验证(resolved/continue) → 归档 → 沉淀经验 | 档案状态迁移、归档视图含处理过程、经验库计数 +1 |
| 持续关注 Watch | 一句话委托 / 暂停 / 检查 | 解析意图 → 显式确认 → 落库 → 频率评估 → 命中回脉搏/升级 | 委托卡片、命中升级后 Pulse/洞察出现引擎判定 |
| 知识库 Knowledge | 按类型筛选复盘 | 归档自动入库 + 经验入库 | 问题/机会/经验 chip 计数与实际条目一致 |
| 全局 | 证据链 / 能力面板 / 专家团 | Evidence 可回溯；专家能力同源展示 | 抽屉字段来自 `/evidence/{id}`；专家来自注册表 |

> 对应代码：`frontend/src/features/{pulse,insight,action,watch,knowledge}`、`components/{dora,layout}`、`services/doraApi.ts`。

---

## 2. 主工作流（Dify 节点图）

### 2.1 触发式主流程（数据更新 / Watch 命中 / 定时）

```mermaid
flowchart TD
  S[Start<br/>trigger: data_update / watch_tick / manual] --> E[HTTP: GET /api/engine/run]
  E --> A[Code: assert_engine_snapshot<br/>schema + 数值锁基线]
  A --> R[Knowledge Retrieval<br/>knowledge_archive + case_lesson]
  R --> C[Question Classifier<br/>intent / kind 路由]
  C -->|problem / opportunity| O[LLM: Supervisor 组队]
  C -->|change| W[HTTP: POST /api/watch<br/>写委托]
  O --> X[Iteration: 专家 Agent 会商回合]
  X --> G[Variable Aggregator<br/>会商纪要 synthesis]
  G --> N[Code: guardrail_numbers<br/>LLM 数字 ⊆ 工具/引擎]
  N -->|pass| H[Human: 人工确认<br/>前端确认/审批]
  N -->|fail| T[Template fallback<br/>回退模板文案 + 记录]
  H --> B[HTTP: POST /api/action/cases<br/>建档]
  B --> P[Iteration: 步骤执行 + 工具调用]
  P --> V[HTTP: POST /api/action/cases/{id}/verify]
  V -->|resolved| L[HTTP: archive-as-lesson + 知识入库]
  V -->|continue| P
  L --> AN[Answer: 页面渲染契约]
  W --> AN
  T --> AN
```

### 2.2 问答子流程（AskBar / FollowupCard → Dora Chat）

```mermaid
flowchart TD
  Q[Start<br/>context + user_question] --> CTX[Code: build_context<br/>page/insight/action/watch/metric]
  CTX --> RET[Knowledge Retrieval<br/>top-k + filters]
  RET --> PA[LLM: 意图分类<br/>为什么/是什么/有哪些机会/帮我处理/给我证据]
  PA --> TL[Agent(ReAct): 选工具<br/>query_* / get_evidence / list_*]
  TL --> EV[Code: evidence assembly]
  EV --> RS[LLM: reasoning + citation]
  RS --> CHK[Code: guardrail_numbers + 引用非空]
  CHK --> ST[SSE: thought_step/tool_call/evidence/answer]
```

> Dify 落地：主流程用 Workflow；问答子流程可用 **Chatflow**（对外暴露 `POST /api/dora/chat`，SSE 事件类型见 §6）。

---

## 3. 节点清单（Dify 节点 → 输入/输出/验证断言）

| # | 节点 ID | Dify 节点类型 | 输入 | 输出 | 验证断言（可自动化） |
|---|---|---|---|---|---|
| 1 | `start` | Start | `trigger`, `workspace`, `page`, `insight_id?`, `question?` | 同左（会话变量） | 必填校验：`trigger∈{data_update,watch_tick,manual,question}` |
| 2 | `engine_snapshot` | HTTP Request | — | `pulse`, `insights[]`（含 metric/delta/confidence/semantics/evidence.kind） | `insights.length≥1`；p1 的 `evidence.kind=="margin"` |
| 3 | `assert_snapshot` | Code | `insights` | `engine_numbers`（白名单数值集）、`snapshot_hash` | 与 golden 基线一致（9 条）；导出白名单供 §3.8 数值锁使用 |
| 4 | `retrieve_knowledge` | Knowledge Retrieval | `query=insight 标题+metric`，`filters={entry_type}` | `chunks[]` + `references[{source_id,code,title}]` | 同 metric 历史 lesson 必须命中；`references` 非空或显式 `"无先例"` |
| 5 | `classify` | Question Classifier / IF-ELSE | `insight.type` | `route∈{action,watch}` | `change→watch`、`problem|opportunity→action`（不允许 LLM 改） |
| 6 | `supervisor` | LLM / Agent | `insight`, `references` | `team[]`（要叫的专家）、`tool_plan[]` | `team ⊆ expert_registry`；每个专家有 `scope` 覆盖命中 metric |
| 7 | `expert_round` | Iteration + Agent | `team[i]`, `tool_plan` | 每个专家 `findings[] / evidence_refs[] / open_questions[]` | 每个 finding 必带 `evidence_ref`（可回溯）；无数字字段 |
| 8 | `aggregate` | Variable Aggregator | 各专家输出 | `synthesis{consensus[],disagreements[],next_steps[]}` | `next_steps.length∈[1,5]`；分歧必须显式记录（不投票定判定） |
| 9 | `guardrail_numbers` | Code | `synthesis` + `engine_numbers` | `pass|fail` | synthesis 中所有数字 ⊆ `engine_numbers ∪ tool_results`；否则 fail |
| 10 | `human_confirm` | Human（或前端确认页） | `synthesis` | `approved` | 未确认不得进入执行（Case 红线：执行=记录驱动） |
| 11 | `create_case` | HTTP Request | `insight_id` | `case{id,code,status}` | `POST /api/action/cases` 200 且 `case.code` 稳定；重复=幂等 |
| 12 | `run_steps` | Iteration + Tool/HTTP | `case.id` | `step{seq,status}` 序列 | 状态机合法：`pending→in_progress→done`；非法迁移 4xx |
| 13 | `verify` | HTTP Request | `case.id`, `outcome`, `note` | `case.status` | `resolved` 要求全步 done + note 非空；已 resolved 再 verify=4xx |
| 14 | `archive` | HTTP Request | `case.id`, `note` | `lesson{created}` | 仅 resolved 可沉淀；重复 `created=false`（幂等） |
| 15 | `publish_watch` | HTTP Request | `text`, `frequency` | `target{id,name}` | 不可解析=显式 4xx + `unsupported[]`（不静默） |
| 16 | `answer` | Answer | 以上聚合 | 页面契约 JSON | 见 §7 场景断言；前端字段来源全部可指回节点输出 |

---

## 4. 多 Agent 设计（专家团 → 角色 Agent）

### 4.1 专家注册表（`expert` 表，对应候选 E1）

```text
expert_id | name | role | kind(problem|opportunity|all) | scope(指标口径[]) | abilities[] | desc | agent(挂载位，默认 null)
```

内置 ≥10 位（经营分析/财务/销售/门店运营/供应链/会员运营/经营增长/商品/数据分析/趋势归因）。**注册表只回答「谁适合处理什么」**，不持有判定权。

### 4.2 编排协议（Supervisor + 角色 Agent）

| 角色 | system prompt 要点 | 允许工具 | 产出 schema | 停止条件 |
|---|---|---|---|---|
| Supervisor | 你是 Dora 会商主持人；**不得产生新判定与新数字**；先读证据再组队 | `get_insight`, `get_evidence`, `retrieve_knowledge` | `team[]`, `tool_plan[]`, `agenda[]` | 组队完成或 3 回合 |
| 经营分析 | 拆解问题结构、给可验证假设 | `query_metric`, `retrieve_knowledge` | findings[]{assumption,evidence_ref,test} | 假设 ≤5 且均有证据引用 |
| 财务 | 口径/成本/利润影响（数字只引用） | `query_metric(supplier_price,margin)` | findings[]{metric_ref,value_ref} | 无新假设 |
| 销售/门店 | 区域/渠道/门店维度定位 | `query_metric(returns,aov,orders)` | findings[]{dimension,evidence_ref} | — |
| 供应链 | 采购/供应商/库存定位 | `query_metric(supplier_price,new_sku)` | findings[]{supplier,price_ref} | — |

**会商回合**（Iteration 节点）：R1 各专家独立意见 → R2 交叉质疑（只能引用对方 evidence_ref）→ Supervisor 汇总 `consensus / disagreements / next_steps`。
**硬约束**：`disagreements` 必须显式保留；不得通过投票改变 `route`/`kind`/数字。

---

## 5. RAG 设计

| 项 | 设计 |
|---|---|
| 语料 | `knowledge_archive`（problem/opportunity/change/lesson）、`case_lesson`、口径与规则（`rule_config` / §15 Metric Definition）、`openspec/specs/*`（行为契约）、可选历史 evidence |
| 元数据（可过滤） | `entry_type`, `code`, `title`, `metric`, `created_at` |
| 切分 | 每行一条 knowledge entry = 1 chunk；长 `content`（处理过程）按段切分并保留 `source_id/code` |
| 检索 | 混合检索 top-k=5 + 元数据过滤（先按 metric/entry_type，再语义） |
| 引用规则 | 每条被使用的 chunk 必须回填 `references[{source_id,code,title}]`；无法引用时输出「无先例」而非编造 |
| grounding 红线 | 检索片段只提供「方法与先例」；**数字仍只能来自工具/引擎**（§7 L2） |
| 评估用例 | ① 同 metric 历史 lesson 必被召回；② references 可回溯到真实行；③ 空语料时输出「无先例」且不阻断主流程 |

> 存储建议：优先 `pgvector`（复用现有 PG，不引新服务）；二期可换独立向量库（Chroma/Qdrant）。

---

## 6. 工具契约（Dify Tool / HTTP 节点）

### 6.1 现有端点可直接作为工具（31 个端点中与本流相关）

> 📌 可直接导入 Dify 的完整 OpenAPI schema + 逐条工具配置，见 **§11 Dify 配置手册**。

| 工具 | 端点 | 用途 | 错误/断言 |
|---|---|---|---|
| `get_engine_snapshot` | `GET /api/engine/run` | 取判定与证据（唯一可信源） | 数值锁基线；503=数据源不可用（不回退演示） |
| `get_pulse` / `list_insights` / `get_insight` | `GET /api/pulse`、`/api/insights?type=`、`/api/insights/{id}` | 总览/列表/详情（含 semantics） | 未命中 404（不静态兜底） |
| `get_evidence` | `GET /api/evidence/{id}` | 证据链（事实→判断→建议） | 404 显式 |
| `list_watch` / `parse_watch` / `create_watch` / `check_watch` / `set_watch_status` / `delete_watch` | `/api/watch*` | 委托生命周期 | 解析失败=4xx+unsupported；重复建=幂等 |
| `list_action_cases` / `get_action_case` / `create_action_case` | `/api/action/cases*` | 建档与读取 | 非引擎判定=400；按 insight_id 幂等 |
| `step_start` / `step_done` / `step_blocked` | `/api/action/cases/{id}/steps/{seq}/*` | 执行回填 | 非法迁移 4xx |
| `verify_action` | `POST /api/action/cases/{id}/verify` | resolved / continue | resolved 需全步 done+note；已 resolved=4xx |
| `archive_as_lesson` / `list_lessons` | `/api/action/cases/{id}/archive-as-lesson`、`/api/action/lessons` | 经验沉淀 | 仅 resolved；重复 created=false |
| `list_knowledge` | `GET /api/knowledge?type=` | 归档检索（RAG 数据面） | stats 与实际一致 |
| `refresh_reasoning` | `POST /api/reason/refresh` | 解释层刷新（不判定） | 无 key=fallback；数值锁 |
| `upload_dataset` / `load_sample` / `current_dataset` | `/api/datasets*` | 数据入口 | 400/413/503 显式；事务替换 |

### 6.2 需要新建的能力（本流落地的前置）

| 待建 | 说明 | 归属候选 |
|---|---|---|
| `query_metric / query_supplier_price / query_returns / …` | 把「指标序列查询」抽成显式工具（现在藏在引擎/证据里），供 Agent 直接调用 | P2-7 工具层 |
| `POST /api/dora/chat`（SSE） | 问答子流程流式：`thought_step / tool_call / evidence / answer` | F8 Dora Chat |
| `POST /api/knowledge/search` | RAG 检索端点（top-k + filters + references） | 本设计 / P2-7 |
| `POST /api/agent/runs` + `GET /api/agent/runs/{id}` | Agent 运行记录（可回放/可审计：节点轨迹、工具调用、token、耗时） | 本设计 |
| job/SSE 状态（Redis/Celery） | 长任务不阻塞请求；前端 `更新中 n/m` | D009 推迟项 / LLM 阶段 2 |
| Confidence Aggregator | 由 6 项输入算 confidence（禁止 prompt 生成） | 引擎侧增强 |

---

## 7. 可验证性设计（本文件的核心）

### 7.1 断言分层（每层独立可测）

| 层 | 断言 | 失败处置 |
|---|---|---|
| L1 结构 | 节点输出符合 JSON schema（`team[]`, `findings[]`, `next_steps[]`） | 重试 1 次 → 失败即 fallback |
| L2 数值锁 | LLM/Agent 输出中的数字 ⊆（引擎 payload ∪ 工具结果） | 拒绝该输出，回退模板文案（`reasonSource=template`） |
| L3 判定锁 | `kind`/`route`/`metric` 只由引擎决定；Agent 不得改写 | 直接判失败并告警 |
| L4 行为 | 落库/终态/幂等：建档幂等、状态机合法、resolved 冻结、lesson 幂等 | 4xx 显式暴露，不伪造成功 |
| L5 引用 | 使用检索片段必须回填 `references`；证据链可回溯到行 | 无引用时显式「无先例」 |

### 7.2 四个 E2E 场景 = Dify Run 用例（对应搭建文档 #36）

| 场景 | 触发/输入 | 期望节点轨迹 | 关键断言 | 前端验收点 |
|---|---|---|---|---|
| Case 1 问题 | `trigger=data_update`，p1 利润率 < 18.5% | engine→assert→retrieval→classify(action)→supervisor→experts→aggregate→guardrail→create_case | `kind=problem`；`case.code` 稳定；落库可见；数字与引擎一致 | 洞察 p1 详情 + 行动回路出现档案 |
| Case 2 机会 | o1 客单价连续 4 周增长 | 同上，`create_case` (opportunity) | `kind=opportunity`；`next_steps` 含「小范围验证可复制性」 | 行动回路出现机会档案 |
| Case 3 变化 | 订单量 -1.8%（未达 -3%） | classify(watch)→`create_watch` | 不建档；委托落库；未命中时保持观察 | 持续关注列表出现委托；Pulse 变化卡 |
| Case 4 升级 | Watch(east_orders) 继续下降至 -3% | watch_tick→engine 判 e2→classify(action)→create_case | 事件 `kind=escalate` 且 `values.engine_insight=="e2"`；委托本身不伪造 problem | Pulse/洞察出现引擎判定 e2；Action 可建档 |

### 7.3 回归与金样本

- **golden 9**：`tests/golden_check.py` 的 9 条洞察快照 = L2/L3 的基线；Dify 侧用 `assert_snapshot` 节点对齐。
- **4 个 E2E**：`tests/e2e_api_check.py` 已固化为 HTTP 用例；Dify Run 用同一输入变量复现。
- **降级矩阵**：无 LLM key→template；检索空→「无先例」；工具 4xx→诚实拒绝；数值断言失败→模板 + 记录。
- **在 Dify 的执行方式**：每个场景一个 Test Run（变量覆盖 dataset/insight_id）→ 在关键节点后接 Code 断言（失败抛错）→ 导出 workflow 版本化 → 记录 run trace 与断言结果。

> 「可验证」的验收标准：**同样输入 + 同样引擎数据 ⇒ 同样判定与同样落库终态**；LLM 只影响文案与建议，不影响 L2/L3 断言。

---

## 8. 与现有仓库的映射与差距

| 层 | 现有（可直接用） | 缺（要新建） |
|---|---|---|
| 判定/E证据 | `backend/app/engine/*`、`/api/engine/run`、`/api/evidence/{id}`、golden 9 | Confidence Aggregator（显式计算） |
| 领域数据 | PG + `models.py`（metric_series/insight_reasoning/watch_target/watch_event/action_case/action_step/case_lesson/knowledge_archive） | `agent` 挂载/运行记录表（agent_run/tool_call） |
| 委托 | `watch/parser|evaluator|scheduler` + `/api/watch*` | 队列化调度（Redis/Celery，多进程前置） |
| 行动 | `action/builder|flow` + `/api/action/cases*` | 工具执行器（真实外部动作，先 mock execution record） |
| 解释 | `reasoning/{provider,llm,semantics,cache,policy}`（模板/LLM 双模，数值锁） | 多 Agent 会商（supervisor+roles）、会商纪要落库 |
| 记忆 | `knowledge_archive`/`case_lesson` + `/api/knowledge` | 向量化 + `/api/knowledge/search`（RAG） |
| 前端 | 5 页 + `doraApi.ts` 三模式；Pulse 已真实化（W1） | `/api/dora/chat` SSE 消费（AskBar/FollowupCard 逐块渲染） |
| 工程 | `run_all` 7 段门禁、`check_docs`、OpenSpec 归档 | job/SSE、Agent run 回放、Dify workflow 版本化导出 |

**降级策略**：暂不做的展示项（Action 列表完成态、页面美化、图表引擎驱动）与本流解耦；它们是"演示质量"，不阻塞 agent 流验证。

---

## 9. 落地顺序（每步都能当场演示）

1. **Step 1（最小闭环）**：Case 1（问题 p1）在 Dify 跑通
   `Start → engine_snapshot → assert_snapshot → retrieve_knowledge → supervisor → 2 experts → aggregate → guardrail_numbers → create_case → answer`
   验收：Dify Run 轨迹可见；`POST /api/action/cases` 落库；前端 Action 抽屉出现新档案。
2. **Step 2（委托/升级）**：Case 3 + Case 4 跑通（parse→create_watch→check→escalate→create_case）。
   验收：Watch 列表与 Pulse 变化卡一致；升级事件引用引擎 insight id。
3. **Step 3（RAG 先例）**：接 `/api/knowledge/search`，让 Step 1 的会商引用历史 lesson（references 非空）。
   验收：同 metric 历史经验被召回并入纪要；引用可回溯。
4. **Step 4（问答 SSE）**：`POST /api/dora/chat` 流式（thought_step/tool_call/evidence/answer）→ 前端 AskBar/FollowupCard 逐块渲染。
5. **Step 5（真实工具 + 回放）**：`/api/agent/runs` 记录轨迹；工具层从 mock 切真实（采购/CRM/IM）；Dify workflow 导出并版本化管理。

---

## 10. 附录

### 10.1 SSE 事件契约（问答子流程）

```text
event: thought_step   data: {"node":"supervisor","text":"正在选择专家…"}
event: tool_call      data: {"tool":"query_metric","args":{...},"status":"ok"}
event: evidence       data: {"refs":[{"source_id":"p1","code":"PRF-0831"}]}
event: answer         data: {"text":"…","references":[...],"number_source":"engine|tool"}
event: done           data: {"run_id":"...","tokens":1234,"latency_ms":2300}
```

### 10.2 Prompt 模板要点（可直接放 Dify LLM/Agent 节点）

- Supervisor：`你是 Dora 会商主持人。禁止产生任何新的业务判定或数值；只能引用提供的引擎字段与工具结果。先读 evidence 再组队。输出 JSON：{team[],tool_plan[],agenda[]}`
- 角色 Agent：`你的职责={role}，适用域={scope}。所有数字必须原样引用工具返回，不得计算/外推。输出 JSON：{findings:[{assumption,evidence_ref,test}],open_questions[]}`
- 汇总：`合并各专家 findings，输出 {consensus[],disagreements[],next_steps[]}。分歧必须保留，不得投票改变 kind/route。`
- 回答：`用中文回答，先给结论再给依据；每条依据标注 references；不得出现未被工具确认的数字。`

### 10.3 速查：节点 → 端点 → 断言

```text
engine_snapshot  → GET /api/engine/run           → insights 数=9、p1.evidence.kind=margin
assert_snapshot  → Code（本地白名单）           → 数值集合 == golden 基线
retrieve         → （待建） /api/knowledge/search → references 非空 或 "无先例"
create_case      → POST /api/action/cases        → 200 + case.code 稳定 + 幂等
run_steps        → POST …/steps/{n}/start|done   → pending→in_progress→done
verify           → POST …/verify                 → resolved 需全 done + note；再验=4xx
archive          → POST …/archive-as-lesson      → created 幂等；knowledge.stats +1
publish_watch    → POST /api/watch               → 落库 + 列表可见；失败=4xx+unsupported
answer           → 前端契约                        → 每字段可指回节点输出
```

### 10.4 维护说明

- 本文件是**设计稿**：改动不需 OpenSpec change，但涉及 backlog/排期的调整请只改 `docs/持续优化路线.md`。
- 在 Dify 里落地时，建议**每个节点 id 与本文件保持一致**（便于断言与回放对齐）；workflow 导出文件另存版本（如 `dify/dora-agent-flow-v1.yml`）。
- 与红线冲突的"捷径"（让 LLM 生成数字/置信度、或让 Agent 改判定）一律不接受——那会让整条流不可验证。

---

## 11. Dify 配置手册（可直接粘贴）

### 11.0 连接信息（先解决"连不上"）

| 项 | 值 / 说明 |
|---|---|
| 后端地址（浏览器 / 宿主机 curl） | `http://localhost:8000/api` |
| **Dify 跑在 Docker**（最常见） | `http://host.docker.internal:8000/api`（macOS / Windows）；Linux 用宿主机内网 IP 或 `--add-host=host.docker.internal:host-gateway` |
| **关键坑**：后端默认只听 127.0.0.1 | 容器访问不到。启动改为：`python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| 鉴权 | 无（本项目未加 API Key）；Dify 自定义工具"鉴权"选 None |
| CORS | 仅允许 `http://localhost:5173`（浏览器直连受限；**Dify 后端调用不受影响**） |
| 数据源不可用 | 503 `{"detail":"data source unavailable"}`（不回落静态演示） |
| 本机 curl 注意 | 加 `--noproxy '*'`（本地代理环境变量会吞请求，见 P 系列） |
| 健康检查 | `GET /api/health` → `{"status":"ok","service":"dora-api"}` |

### 11.1 OpenAPI Schema（Dify「自定义工具 → 导入 OpenAPI」直接粘贴）

> 用途：一次性把下面所有端点导入成 Dify 工具集；导入后在每个工具里改 **Base URL** 为你的环境（§11.0）。
> 若只想用部分工具，删掉对应 `paths` 即可。

```yaml
openapi: 3.0.0
info:
  title: Dora API (Agent Tools)
  version: "1.0.0"
  description: Dora 判定/证据/委托/行动/知识 REST —— Agent 流只读工具 + 受控写工具
servers:
  - url: http://host.docker.internal:8000/api   # Dify in Docker（改成本机情况下的 http://localhost:8000/api）
paths:
  /health:
    get:
      operationId: dora_health
      summary: 健康检查
      responses: { "200": { description: ok } }
  /engine/run:
    get:
      operationId: get_engine_snapshot
      summary: 引擎快照（判定+证据，唯一可信源）
      responses: { "200": { description: "{ pulse, insights[] }" }, "503": { description: 数据源不可用 } }
  /pulse:
    get:
      operationId: get_pulse
      summary: 业务脉搏计数
      responses: { "200": { description: "{ problems, opportunities, changes, watching, last_updated }" } }
  /insights:
    get:
      operationId: list_insights
      summary: 洞察列表（按类型）
      parameters:
        - name: type
          in: query
          required: false
          schema: { type: string, enum: [problem, opportunity, change], default: problem }
      responses: { "200": { description: "Insight[]（含 semantics/reasonSource/evidence.kind）" } }
  /insights/{insight_id}:
    get:
      operationId: get_insight
      summary: 洞察详情（含 route/trigger/factors/evidence/semantics）
      parameters:
        - name: insight_id
          in: path
          required: true
          schema: { type: string }
      responses: { "200": { description: Insight detail }, "404": { description: 不在当前引擎判定集 } }
  /evidence/{evidence_id}:
    get:
      operationId: get_evidence
      summary: 证据链（事实→判断→建议 + 原始行）
      parameters:
        - name: evidence_id
          in: path
          required: true
          schema: { type: string }
      responses: { "200": { description: EvidenceModel }, "404": { description: not found } }
  /watch:
    get:
      operationId: list_watch
      summary: 委托列表（卡片）
      responses: { "200": { description: "WatchCard[]" } }
    post:
      operationId: create_watch
      summary: 创建委托（解析失败 400）
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [text]
              properties:
                text: { type: string, example: "帮我关注华东销售额，如果连续三天下降就提醒我" }
                frequency: { type: string, enum: ["on_update", "daily 09:00", "weekly"] }
      responses: { "200": { description: "{ ok, target }" }, "400": { description: 无法解析（返回 unsupported 原因） } }
  /watch/parse:
    post:
      operationId: parse_watch
      summary: 仅解析委托（不落库，供确认界面）
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [text]
              properties:
                text: { type: string }
      responses: { "200": { description: "{ ok, intent{metric_key,dimension,condition,frequency,label,condition_defaulted}, unsupported[] }" } }
  /watch/{watch_id}:
    get:
      operationId: get_watch
      summary: 委托详情（含命中事件）
      parameters:
        - { name: watch_id, in: path, required: true, schema: { type: string } }
      responses: { "200": { description: "{ ok, target, events[] }" }, "404": { description: not found } }
    patch:
      operationId: set_watch_status
      summary: 暂停/恢复委托
      parameters:
        - { name: watch_id, in: path, required: true, schema: { type: string } }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [status]
              properties:
                status: { type: string, enum: [watching, paused] }
      responses: { "200": { description: "{ ok, target }" }, "404": { description: not found } }
    delete:
      operationId: delete_watch
      summary: 删除委托（幂等）
      parameters:
        - { name: watch_id, in: path, required: true, schema: { type: string } }
      responses: { "200": { description: "{ ok, deleted }" } }
  /watch/{watch_id}/check:
    post:
      operationId: check_watch
      summary: 立即评估一次（命中 change/escalate/miss）
      parameters:
        - { name: watch_id, in: path, required: true, schema: { type: string } }
      responses: { "200": { description: "{ ok, kind: change|escalate|miss, ... }" }, "404": { description: not found } }
  /action/cases:
    get:
      operationId: list_action_cases
      summary: 行动档案列表（摘要，无 steps）
      responses: { "200": { description: "{ ok, cases[] }" } }
    post:
      operationId: create_action_case
      summary: 为引擎判定的洞察建档（按 insight_id 幂等；非判定 400）
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [insight_id]
              properties:
                insight_id: { type: string, example: p1 }
      responses: { "200": { description: "{ ok, created, case }" }, "400": { description: 只允许当前引擎判定的 problem/opportunity } }
  /action/cases/{case_id}:
    get:
      operationId: get_action_case
      summary: 档案详情（含步骤/编排/归档文本）
      parameters:
        - { name: case_id, in: path, required: true, schema: { type: string } }
      responses: { "200": { description: "{ ok, case }" }, "404": { description: not found } }
  /action/cases/{case_id}/steps/{seq}/start:
    post:
      operationId: step_start
      summary: 开始步骤（pending|blocked → in_progress）
      parameters:
        - { name: case_id, in: path, required: true, schema: { type: string } }
        - { name: seq, in: path, required: true, schema: { type: integer } }
      responses: { "200": { description: "{ ok, case }" }, "400": { description: 非法迁移 } }
  /action/cases/{case_id}/steps/{seq}/done:
    post:
      operationId: step_done
      summary: 完成步骤（in_progress → done，带 note/result）
      parameters:
        - { name: case_id, in: path, required: true, schema: { type: string } }
        - { name: seq, in: path, required: true, schema: { type: integer } }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                note: { type: string }
                result: { type: string }
      responses: { "200": { description: "{ ok, case }" }, "400": { description: 非法迁移 } }
  /action/cases/{case_id}/steps/{seq}/blocked:
    post:
      operationId: step_blocked
      summary: 标记受阻（in_progress → blocked）
      parameters:
        - { name: case_id, in: path, required: true, schema: { type: string } }
        - { name: seq, in: path, required: true, schema: { type: integer } }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                note: { type: string }
      responses: { "200": { description: "{ ok, case }" }, "400": { description: 非法迁移 } }
  /action/cases/{case_id}/verify:
    post:
      operationId: verify_action
      summary: 验证归档（resolved 需全步 done + note；continue=继续观察）
      parameters:
        - { name: case_id, in: path, required: true, schema: { type: string } }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [outcome]
              properties:
                outcome: { type: string, enum: [resolved, continue] }
                note: { type: string, example: "利润率回到 18.6%，验证通过" }
      responses: { "200": { description: "{ ok, case }" }, "400": { description: 未全步 done / 缺 note / 已 resolved } }
  /action/cases/{case_id}/archive-as-lesson:
    post:
      operationId: archive_as_lesson
      summary: 沉淀经验进经验库（仅 resolved；幂等）
      parameters:
        - { name: case_id, in: path, required: true, schema: { type: string } }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                note: { type: string, example: "供应商 B 成本需季度复核" }
      responses: { "200": { description: "{ ok, created, lesson }" }, "400": { description: 非 resolved 或空结论 } }
  /action/lessons:
    get:
      operationId: list_lessons
      summary: 经验库列表
      responses: { "200": { description: "{ ok, lessons[] }" } }
  /knowledge:
    get:
      operationId: list_knowledge
      summary: 知识/归档库（按类型筛选 + 各类型计数）
      parameters:
        - name: type
          in: query
          required: false
          schema: { type: string, enum: ["", problem, opportunity, change, lesson], default: "" }
      responses: { "200": { description: "{ ok, type, entries[], stats{problem,opportunity,change,lesson} }" } }
  /reason/refresh:
    post:
      operationId: refresh_reasoning
      summary: 刷新解释文案（不改判定；无 LLM key 自动回退模板）
      responses: { "200": { description: "刷新结果（前端读 provider / updated；字段以实际响应为准）" } }
```

### 11.2 逐条工具配置表（HTTP 节点 / 自定义工具）

| Dify 工具名 | 方法 + 路径（相对 `/api`） | 请求 | 关键响应字段 | 断言 / 错误 |
|---|---|---|---|---|
| `get_engine_snapshot` | `GET /engine/run` | — | `pulse`, `insights[]` | `insights.length==9`；`insights[i].evidence.kind` 存在 |
| `get_pulse` | `GET /pulse` | — | `problems/opportunities/changes/watching` | `problems == insights(problem).length` |
| `list_insights` | `GET /insights?type=` | query `type` | `Insight[]`（含 `semantics`、`reasonSource`） | 枚举合法；空数组是合法结果 |
| `get_insight` | `GET /insights/{insight_id}` | path | `route/trigger/factors/evidence/semantics` | 404 = 不在判定集（**不许回退静态**） |
| `get_evidence` | `GET /evidence/{evidence_id}` | path | `fact/judgment/suggestion/hits/rawRows` | `rawRows` 非空 |
| `list_watch` | `GET /watch` | — | `WatchCard[]` | 卡片含 `name/value/color/logic/status` |
| `parse_watch` | `POST /watch/parse` | `{text}` | `ok/intent/unsupported` | `ok=false` 时必须读 `unsupported[0].reason` |
| `create_watch` | `POST /watch` | `{text, frequency?}` | `{ok,target}` | 400=不可解析；成功后 `GET /watch` 可见 |
| `check_watch` | `POST /watch/{id}/check` | — | `kind∈{change,escalate,miss}` | `escalate` 必须带引擎 insight id |
| `list_action_cases` | `GET /action/cases` | — | `{ok,cases[]}` | 摘要无 steps（详情另取） |
| `create_action_case` | `POST /action/cases` | `{insight_id}` | `{ok,created,case}` | 重复=幂等；非判定 400 |
| `get_action_case` | `GET /action/cases/{id}` | path | `{ok,case}`（含 steps/status/orchestration） | `status∈{open,running,waiting_verify,resolved}` |
| `step_start/done/blocked` | `POST …/steps/{seq}/…` | `{note,result}`（done/blocked） | `{ok,case}` | 非法迁移 400 |
| `verify_action` | `POST …/verify` | `{outcome,note}` | `{ok,case}` | resolved：全步 done+note；已 resolved 400 |
| `archive_as_lesson` | `POST …/archive-as-lesson` | `{note}` | `{ok,created,lesson}` | 仅 resolved；重复 `created=false` |
| `list_knowledge` | `GET /knowledge?type=` | query `type` | `entries[]`, `stats` | `stats.* == 对应 entries 计数` |
| `refresh_reasoning` | `POST /reason/refresh` | — | `provider`, `updated` | 无 key 时 `provider=template`（不报错） |

> 通用约定：写操作 **业务 4xx 一律显式上抛**（Dify 节点"失败重试"设 **0 次**，避免把拒绝吞成成功）；`503` = 数据源不可用，不要重试成"成功"。
> 时间/网络：本地 curl 加 `--noproxy '*'`；Dify 节点超时建议 15s（`/reason/refresh` 真实 LLM 批量可到 30s，改 60s）。

### 11.3 知识库（RAG）配置

**① Dora 侧导出语料为 JSONL**（Dify 知识库按行导入）：

```bash
curl -sS --noproxy '*' 'http://localhost:8000/api/knowledge' | python3 -c "
import json,sys
d=json.load(sys.stdin)
for e in d['entries']:
    print(json.dumps({
      'name': e['entry_type'] + '-' + e['code'],
      'text': (e['title'] + '\n' + e['content'] + '\n结论：' + e['note']).strip(),
      'metadata': {'entry_type': e['entry_type'], 'code': e['code'], 'source_id': e['source_id'], 'created_at': e['created_at']}
    }, ensure_ascii=False))
" > dora_knowledge.jsonl
```

经验库同理：`GET /api/action/lessons` → 映射 `case_id/code/title/archive/resolution`。

**② Dify 知识库设置建议**

| 项 | 建议值 |
|---|---|
| Embedding 模型 | `bge-m3`（本地）或 `text-embedding-3-small`（API） |
| 分段 | 自定义：分隔符 `\n`，最大 512 tokens，overlap 50（knowledge 条目天然短） |
| 索引 | 高质量（high_quality） |
| 检索 | 向量检索 top-k=5，score 阈值 0.5，**开启"引用/Retrieval 返回 references"** |
| 元数据 | 保留 `entry_type / code / source_id / created_at`（检索节点可加过滤） |
| 增量 | 每次 archive-as-lesson 后重跑导出 → Dify 知识库"重新索引"（或定时） |

**③ 检索节点参数**：query = `{{#insight.title#}} {{#insight.metric#}}`；filters = `entry_type in (lesson, problem, opportunity)`；输出 `chunks[] + references[]`（§5 引用红线）。

### 11.4 Workflow 变量与节点映射（Dify 里照抄）

| 变量 | 类型 | 来源 | 示例 | 用在哪 |
|---|---|---|---|---|
| `trigger` | string | Start 输入 | `data_update` / `watch_tick` / `question` | 路由分支 |
| `insight_id` | string | Start 输入 / 上游节点 | `p1` | 选洞察 |
| `question` | string | Start 输入 | `为什么利润率会失速？` | 问答子流程 |
| `pulse` | object | `{{#engine_snapshot.body.pulse#}}` | `{problems:3,...}` | Pulse 计数 |
| `insights` | array | `{{#engine_snapshot.body.insights#}}` | 9 条 | 选洞察/信号板 |
| `insight` | object | Code 节点：`insights.filter(i=>i.id==insight_id)[0]` | p1 | 主区/supervisor |
| `references` | array | 知识库检索节点 | `[{source_id,code}]` | 会商引用 |
| `synthesis` | object | 汇总节点 | `{consensus,disagreements,next_steps}` | 人工确认/建档 |
| `case_id` | string | `{{#create_case.body.case.id#}}` | `p1` | 步骤执行/验证 |

**页面契约回填**（Answer/End 节点的输出字段）：
`pulse_counts` → Pulse 计数卡；`hero{copy,facts,note}` → 主区；`signal_rows[]` → 信号板；`monitor_rows[]` → 监控卡；`case{id,code,status}` → 行动档案；`watch{id,name}` → 持续关注；`knowledge_refs[]` → 知识库引用。

> Dify 变量引用语法：`{{#节点ID.字段路径#}}`；HTTP 节点响应体在 `body` 下（如 `{{#engine_snapshot.body.insights#}}`）。

### 11.5 LLM / Agent 节点参数

| 项 | 值 |
|---|---|
| 模型供应商 | DeepSeek：Base `https://api.deepseek.com/v1`，Model `deepseek-chat`（需支持 tool calling） |
| 生成参数 | temperature `0.2`（结构化输出）；max_tokens `1500`；失败重试 1；超时 60s |
| Agent 节点（ReAct） | max_iterations **3–5**；开 tool calling；**工具白名单**：只读工具给所有专家；`create_* / step_* / verify_*` 只挂到 supervisor 与执行节点 |
| 结构化 | 开 JSON 输出（如供应商支持）→ 后接 Code 断言（§7 L1/L2） |
| 兜底 | 无 key / 断言失败 → 走"模板文案"分支（与后端 `reasonSource=template` 对齐），不阻断主流程 |

### 11.6 还没建的能力 → 先用什么替代

| 缺口 | 临时替代（现在就能跑） | 正式方案 |
|---|---|---|
| RAG 检索端点 | Dify 自带"知识库检索"节点（数据来自 §11.3 导出） | `POST /api/knowledge/search` |
| 问答流式 SSE | Dify **Chatflow** 的 Answer 节点（原生流式） | `POST /api/dora/chat`（thought_step/tool_call/evidence/answer） |
| `query_*` 指标时序工具 | `get_insight` + `get_evidence` + `list_insights` 组合 | `/api/tools/query_metric`（P2-7） |
| 长任务/进度 | Dify 工作流串行执行（节点耗时可视） | job + SSE（D009 / LLM 阶段 2） |
| 运行回放/审计 | Dify 自带 Run 记录 + 导出的 workflow YAML 版本化 | `POST/GET /api/agent/runs` |

### 11.7 配置完成后的冒烟（先逐条点，再跑 Case 1）

```bash
curl -sS --noproxy '*' localhost:8000/api/health
curl -sS --noproxy '*' localhost:8000/api/engine/run  | python3 -c "import json,sys;d=json.load(sys.stdin);print('insights',len(d['insights']))"
curl -sS --noproxy '*' 'localhost:8000/api/insights?type=problem' | python3 -c "import json,sys;print([(i['id'],i.get('evidence',{}).get('kind')) for i in json.load(sys.stdin)])"
curl -sS --noproxy '*' localhost:8000/api/watch/parse -H 'Content-Type: application/json' -d '{"text":"关注利润率，连续 3 天下跌提醒我"}'
curl -sS --noproxy '*' localhost:8000/api/knowledge | python3 -c "import json,sys;print(json.load(sys.stdin)['stats'])"
```

期望：`health=ok`；`insights=9`；p1 的 `evidence.kind=margin`；parse `ok=true / metric_key=margin`；knowledge `stats` 与页面 chip 计数一致。

Dify 侧验收顺序：每个工具"测试"按钮通过 → 跑 **Case 1（问题 p1）** → `assert_snapshot` / `guardrail_numbers` 不报错 → `create_action_case` 成功 → 打开前端「行动回路」能看到新档案（这就是"可验证"的最小闭环）。





