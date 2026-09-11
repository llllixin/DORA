## Context

迭代 43（`insight-panel-polish`）刚把判断列收敛为「不复述其它区块」的单一结论段，判断列现在只有：AI 判断原文（`POST /api/dora/chat`）+ 置信度。本轮要在同一区域补「严重等级」与「可能后果」两段——即**判断列从一段扩为三段**，且新增内容必须与迭代 43 的去复述规则共存（见 proposal.md - Why）。

关键现状（已核对，非推测）：

- `INSIGHT_TEMPLATES`（`app/engine/engine.py:281`）的 `tag` 承载等级文案（`问题 · 高影响` / `问题 · 中影响` / `问题 · 需复核`），是**写死字符串**，与数值无关。
- 引擎快照 `compute_snapshot()` 已含判级所需的全部原始量：`margin{current,baseline,target,delta_pct,streak_below}`、`returns{baseline,delta_pp,rising_weeks,stores[],latest_store{}}`、`east_orders{current,delta_pct,threshold}`、`high_value{current,baseline,delta_pp}`、`new_sku{delta_pct}`、`aov{current,delta_pct}`、`orders{current,delta_pct}`、`data_event{rows_added,updated,metrics[]}`、`store_cluster{ratio,threshold,region_count,top_total,mix_pct}`、`supplier_b{current,delta_pct,peer_delta_pct}`。
- `reasoning` 缓存只覆盖 `semantics`（`_apply_reasoning_cache`），**不会**覆盖新字段——新字段必须每次由引擎现算，才能保证「确定性 + 可回溯」。
- 前端判断列数据源有三处：`/api/insights` 同步结构、`data.ts` 离线镜像（9 条，无新字段）、`/api/dora/chat` 散文。新字段只能落在**引擎字段**这一路，才能同时覆盖在线与离线。
- chat 侧 `InsightPage` 发送的问题是 `x.question`（如「成本上涨集中在哪个供应商？」→ 实测 `intent=what`）。

## Goals / Non-Goals

**Goals:**

- `severity` / `consequence` 成为**引擎契约的一部分**：可断言、可回溯、确定性、与 `tag` 文案解耦。
- 判级规则**显式可解释**：`rule` 文案里说明「本次为何是这个等级」，而不是只给一个数字。
- 判断列三段式在**在线/离线/降级**三条路径下都成立（离线镜像与降级兜底不得出现空白段或臆造数字）。

**Non-Goals:**

- 不给 `severity` 做后台可配置阈值（权重集中在一处常量即可，配置化属后续候选）。
- 不改 `tag` 文案、不改 Pulse 计数、不改 Action/Watch 页面。
- 不让 LLM 参与判级/外推（LLM 只继续负责 `semantics` 解释，D014/D028 不变）。
- 不做「严重度时间序列/趋势图」（需要历史快照，另立候选）。

## Decisions

### D1｜判级 = 显式加权规则（`base + max(趋势, 阈值) + 持续 + 影响面 + 归因面`），权重集中在 `SEVERITY_WEIGHTS`

- **做法**：`_severity(sig, snap)` 纯函数，输入信号 + 快照，输出 `{level, score, rule, drivers, basis:'engine'}`。
  - `base`：problem 50 / opportunity 45 / change 25（类型决定基本盘）。
  - `trend`（按量纲分档）：百分比 `|d| ≥10→20 / ≥5→14 / ≥3→10 / ≥1.5→6 / else 2`；百分点 `|d| ≥5→20 / ≥3→14 / ≥1.5→10 / else 5`。
  - `threshold`（距阈值/越线）：已越线（跌破问题阈值或越过机会阈值）→12；距阈值 ≤1pp →8；≤2pp →5；否则 0。
  - `duration`：连续天数/周数 `min(n,6) × 1.5`。
  - `impact`：受影响门店数/指标数/区域门店数 `min(n,4) × 2`。
  - `attribution`：`min(len(factors),3) × 2`。
  - `score = min(99, base + max(trend, threshold) + duration + impact + attribution)`；`level`：`≥75 high / 55–74 medium / else low`。
- **为什么 `max(trend, threshold)` 而不是相加**：「偏离幅度」与「距阈值距离」度量同一件事（离常态有多远），相加会让同一事实被计两次，等级虚高且难解释。
- **`drivers` 只放参与判级的快照值**（如 `连续低于目标 4 天`、`偏离目标 5.4%`、`距升级阈值 0.9pp`、`受影响门店 2 家`），`rule` 用同一批 driver 名称拼一句人话（如 `问题且偏离目标 5.4%、连续 4 天、已低于目标线`）。
- **实测分布**（当前数据集，用于验收对照）：`p1=high`；`p2 / p3 / o1 / o2 / e2=medium`；`c1 / c2 / c3 / c4=low`。`c1(low) ≤ e2(medium)` 满足「未达阈值不高过已升级」。
- **备选（否决）**：用 LLM 判级 → 不确定、不可测、违 D011/D014；直接把 `tag` 文案映射成等级 → 就是现状，「写死」问题未解决；引入历史快照算斜率 → 需要新数据源（超范围）。

### D2｜后果 = 确定性外推（模板 × 快照数字），无趋势字段时输出定性后果

- **做法**：`_consequence(sig, snap)` 纯函数，按 `sig["insight"]`（p1/p2/p3/o1/o2/c1/c2/c3/c4/e2）取分支，输出 `{summary, horizon, condition, impacts[], basis:'engine'}`。
  - `summary`：类型化句式 + 快照数字，例如 p1 → `若不干预，利润率将延续 5.4% 的偏离幅度，成本端压力继续放大（A 产品线采购成本 2.2%、供应商 B 高于同行 10.9%）`；c1 → `订单量再走弱 0.9pp 即触及 -3.0% 升级阈值，将自动升级为问题`。
  - `horizon`：优先用快照里的持续量（`streak_below`/`rising_weeks`/新品周数）取 `max(n,3)` 天/周；无则给类型默认窗口（problem 3 天 / opportunity 2 周 / change 5 天）。
  - `condition`：外推前提的显式声明（`若成本端未干预` / `若趋势延续` / `若可复制性成立`）。
  - `impacts`：1–3 项，值只用快照数字（如 `目标线 18.5%`、`距升级阈值 0.9pp`、`受影响指标 4 项`）。
  - **证据不足路径**：`c2`（数据更新事件）无趋势字段 → `summary` 定性（`数据事件本身不构成经营后果；重算后若指标触发阈值，将生成对应洞察`）、`impacts` 只放 `受影响指标` 计数（来自 `data_event.metrics`），**不造新数字**。
- **为什么不用 LLM 生成后果**：后果要能被用户当作承诺核对，必须可回溯；LLM 数字会破坏数字锁（`number_source:'engine'`）。
- **备选（否决）**：`consequence` 只给定性一句话（不含数字）→ 对「不处理会怎样」帮助有限，用户要的是可核对的量化边界；用图表数据（`frontend/src/data.ts` 的 `chartData`）做外推 → 那是前端静态数据、非引擎来源（F11 候选），不能作为判断依据。

### D3｜判断列三段式的数据源分工：等级/后果来自引擎字段，散文判断仍来自 chat

- **做法**：
  - 段① 严重等级：`x.severity`（引擎字段）→ 徽章 `high/medium/low` + `score` + `rule` + `drivers`（chips）。
  - 段② 为什么发生：沿用现状 `askDora(x.question)` 的散文原文（`lead` + 去复述后的 `ownRest`），问题**不改成 why 句式**。
  - 段③ 可能后果：`x.consequence`（引擎字段）→ `summary` + `condition`/`horizon` + `impacts` 小表。
  - `chat` 新增 `consequence` 意图只为 AskBar 追问（用户问「不处理会怎样」时给出 `严重等级：`/`可能后果：` 两段），**不参与**判断列常驻渲染。
- **为什么段②不改问 why**：why 句式会让答案带 `主要影响因素：`/`进一步定位：`，而这两行按迭代 43 的 `belongsElsewhere` 归到左栏归因卡 → 判断列只剩结论句，白忙一场；保持 `x.question` 反而稳定。
- **为什么等级/后果不走 chat**：离线镜像（`data.ts`）、`VITE_API_MODE=mock`、AI 不可用三种场景下 chat 都不可用；若等级/后果依赖 chat，则三种场景同时丢两段（与迭代 43 已建立的「降级仍完整」原则冲突）。
- **四段不重复的边界**：`严重等级：` / `可能后果：` 是 chat 侧的**新前缀**，需加入 `belongsElsewhere` 前缀表（各自归位到段①/段③），从而满足「展开补充说明也不重复」。

### D4｜兼容与迁移：增量字段 + 可选类型 + 离线镜像同步补值

- 后端：`severity`/`consequence` 追加进 `build_insights()` 的洞察字典（**不入库**，每算每出）；`tag`、`semantics`、`pulse`、证据链一律不动 → golden 9 / `pulse 3/2/4/4` 基线不应变化；`engine_check` 只新增字段级断言。
- 前端：`types.ts` 中 `severity?`/`consequence?` 为**可选**；渲染用 `x.severity ? … : null`，缺字段时退回「现有判断列」（迭代 43 形态），不出现空壳区块。
- 离线镜像：`frontend/src/data.ts` 的 9 条镜像按**同一口径**补 `severity`/`consequence`（数值与引擎一致，作为镜像常量写死，注释标注「镜像自迭代 44 引擎输出，引擎口径变化需同步」），避免离线态与在线态判级不一致。
- 无 DB 迁移、无接口删除、无环境变量新增。

## Risks / Trade-offs

- **[判级口径被质疑「为什么不是 high」] → 缓解**：`rule` + `drivers` 把判级依据直接摆在卡片上；权重集中在 `SEVERITY_WEIGHTS` 常量，改口径 = 改一处数值 + 跑 `engine_check`。
- **[判级是启发式，非财务口径] → 缓解**：spec 只锁「结构性行为」（覆盖、可回溯、确定性、观察项 ≤ 已升级项、随数据变化），不锁具体分数；`rule` 文案明示这是引擎启发式。
- **[三段式让判断列变高，与左栏等高/贴底规则冲突] → 缓解**：判断列仍在 `.judge-col` 内，`verdict-conf{margin-top:auto}` 继续贴底；高度由较高一栏决定，左栏事实卡自然等高（迭代 43 的像素断言沿用）。
- **[后果文案与外推值被当成承诺] → 缓解**：每段强制输出 `condition` + `horizon`（前提与窗口），`summary` 固定以「若…」开头。
- **[镜像 `data.ts` 与引擎口径漂移] → 缓解**：镜像注释标注来源与同步要求；任务加一条断言「镜像 9 条的 `severity.level` 与引擎输出同名同值」。
- **[chat 新增意图抢占既有词] → 缓解**：`consequence` 关键词限定为「后果/不处理/会怎样/风险/影响面」，并加回归断言「为什么 / 证据 问题仍分别命中 `why` / `evidence`」。

## Migration Plan

1. 后端：`engine.py` 加 `SEVERITY_WEIGHTS` + `_severity()` + `_consequence()`，接进 `build_insights()` → `engine_check` 新断言全绿且 `pulse`/golden 不变。
2. chat：`CHAT_INTENT_RULES` 加 `consequence`，`_compose_answer` 加分支 → 三问（为什么 / 证据 / 不处理）意图与段落各归其位。
3. 前端：`types.ts` → `InsightPage.tsx` 三段式 → `data.ts` 镜像补值 → `styles.css` 徽章样式 → `npm run build` + CDP 断言（三视口、去复述、离线/降级路径）。
4. 回滚：前端字段可选 + 引擎字段增量 → 只回滚前端渲染即恢复迭代 43 形态；后端回滚删两个函数与两处接线（无数据迁移、无外部依赖）。
