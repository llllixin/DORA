## Why

洞察页的「判断」区域目前只回答「是什么/为什么」，答不出经营上最要紧的两问：**有多严重**、**不处理会怎样**。2026-09-11 用户实测提出：判断应当是「严重等级 → 为什么发生 → 可能后果」三段式。

迭代 43 核对后的现状缺口（两条都是**硬缺口**，不是文案问题）：

- **等级不由数据计算**：严重程度只以文案形式写死在 `backend/app/engine/engine.py` 的 `INSIGHT_TEMPLATES`（`问题 · 高影响` / `问题 · 中影响` / `问题 · 需复核` …），与偏离幅度、持续天数、距阈值距离、影响面**无关**——同一套数据下无法解释「为什么它是高影响」。
- **后果字段与意图均不存在**：全仓无 `consequence`；`CHAT_INTENT_RULES` 只有 `why/evidence/opportunity/delegate/handle`，用户问「不处理会怎样」只会落回 `what` 泛化回答。

价值：判断列从「解释已发生」升级为「解释已发生 + 量化严重度 + 说明不处理的外推后果」，同时保持 D011（判断归后端）与数字锁（前端不产生新数字）。

## What Changes

- **引擎新增两个增量字段**（每条洞察都带，camelCase，与前端 TS 类型同源）：
  - `severity`：`{ level: 'high'|'medium'|'low', score: 0-100, rule: string, drivers: [{ name, value }], basis: 'engine' }` —— 由**同一份引擎快照**按显式规则计算（偏离幅度 / 持续天数 / 距阈值距离 / 影响面），`drivers` 的值只引用快照里已有的数字。
  - `consequence`：`{ summary, horizon, condition, impacts: [{ name, value }], basis: 'engine' }` —— 按当前趋势做**确定性外推**（不引入 LLM 数字、不引入快照外数据）；`horizon`（观察窗口，如 `3 天`）与 `condition`（成立条件，如 `若趋势延续`）说明外推前提。
- **chat 支持「后果」一问**：`CHAT_INTENT_RULES` 新增 `consequence` 意图（触发词：后果/影响/不处理/会不会/风险/继续下去）；`_compose_answer` 在 `why`/`consequence` 下产出**带固定前缀**的段落（`严重等级：…` / `可能后果：…`），供前端按段归位、避免与既有段落重复。
- **前端判断列改三段式**：① 等级徽章（`severity.level` + `rule`/`drivers` 摘要）② 为什么发生（现状 AI 判断/引擎语义原文）③ 可能后果（`summary` + `condition` + `impacts`）。继续遵守迭代 43 的**去复述**规则：某段若已由其它区块承载（下一步建议/归因卡/历史先例），判断列不重复。
- **兼容策略（增量，不破坏现状）**：`tag` 文案保留不动（其它页面与 golden 基线不受影响）；`severity`/`consequence` 在前端类型里为**可选**，缺失时（mock / 离线镜像 / 旧缓存）整段不渲染或退回现有判断列渲染。

**BREAKING**：无。`GET /api/insights*` 响应为**纯增量**字段；未消费方无需改动。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `business-engine`: 新增两条能力需求 —— ①洞察严重等级 SHALL 由数据结构化计算并随洞察下发（不得为写死文案）；②洞察可能后果 SHALL 由引擎按当前快照确定性外推、且其数字全部可回溯到快照（数字锁）。
- `business-agent`: 新增一条能力需求 —— Dora Chat SHALL 支持 `consequence`（后果）意图，答案段落带可识别前缀，且不重复其它意图已有的信息。

## Impact

- **后端**
  - `app/engine/engine.py`：`build_insights()` 组装 `severity`/`consequence`；新增纯函数 `_severity(sig, snap)`、`_consequence(sig, snap)`（同 `_confidence` 风格）；`INSIGHT_TEMPLATES.tag` 保持不动。
  - `app/routers.py`：`CHAT_INTENT_RULES` + `_compose_answer` 新增 `consequence` 分支与前缀段落。
  - `tests/engine_check.py`：新增 `severity`/`consequence` 契约断言（9 条洞察全覆盖、`basis='engine'`、数字 ∈ 快照、level 与规则一致），并保持 `pulse 3/2/4/4` 与 golden 9 基线不变。
- **契约**：`GET /api/insights`、`GET /api/insights/{id}`、`POST /api/dora/chat`(answer 文本) 增量变化；camelCase；无 DB 迁移（字段是计算结果，不入库；`reasoning` 缓存仍只覆盖 `semantics`）。
- **前端**：`frontend/src/types.ts`（`InsightSeverity`/`InsightConsequence` 可选字段）、`frontend/src/features/insight/InsightPage.tsx`（三段式渲染 + 行归类正则扩展）、`frontend/src/data.ts`（离线镜像 9 条按同一口径补字段或显式走回退）、`frontend/src/styles.css`（等级徽章样式）。
- **文档**：dev-log 追加「迭代 44」、`docs/持续优化路线.md` 勾选本项、`docs/开发问题与经验.md` 记 D 系列（等级/后果口径与退出条件）。
- **非目标**：不改 Pulse/Action/Watch 页面结构；不引入 LLM 生成数值；不做 severity 的可配置阈值后台（后续候选）。
