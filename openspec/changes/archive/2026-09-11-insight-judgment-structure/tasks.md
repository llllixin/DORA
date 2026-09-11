## 1. 引擎：洞察严重等级（severity）

- [x] 1.1 `app/engine/engine.py` 新增 `SEVERITY_WEIGHTS`（base/trend/threshold/duration/impact/attribution 分档与 level 切点，见 design D1）与纯函数 `_severity(sig, snap)`，并在 `build_insights()` 的洞察字典中下发 `severity` → 验证：`cd backend && python3 -c "from app.engine.engine import run_engine; i={x['id']:x for x in run_engine()['insights']}; print([(k, v['severity']['level'], v['severity']['score']) for k, v in sorted(i.items())])"`（本机 `python3` = `/Users/tomara/miniforge3/bin/python3`，P012） → 实测：`[('c1','low',37),('c2','low',35),('c3','low',49),('c4','low',49),('o1','medium',59),('o2','medium',67),('p1','high',76),('p2','medium',74),('p3','medium',64)]`——与 design D1「实测分布」逐条一致；**命令按实况纠正**（原稿 `assert i['e2']['severity']['level']=='medium'`）：当前种子 `east_orders.delta_pct=-2.1` 未跌破 `-3.0` → 只产 `c1`（`c1`/`e2` 是同一信号的互斥分支，见 P016），故改为断言 `p1=high`、`c1=low` 且 9 条分布与 D1 一致；`e2` 的对照改用注入式断言（1.4）
- [x] 1.2 `rule` 与 `drivers` 可读且可回溯：`rule` 非空、`drivers` 至少一项（`{name, value}`），且 `drivers[*].value` 中出现的数字均能在该洞察 payload（`metric/delta/desc/semantics/trigger`）或快照派生值中找到对应 → 验证：逐条断言 + 人工读一遍 `p1` 的 `rule` 文案 → 实测：p1 `rule = 引擎启发式 · 问题：偏离目标 5.4%、距目标线 已越线、连续低于目标 4 天、受影响供应商 1 家、归因因素 2 项`；drivers 5 项（`偏离目标 5.4%` / `距目标线 已越线` / `连续低于目标 4 天` / `受影响供应商 1 家` / `归因因素 2 项`）；数字锁断言（`drivers` 数字 ⊆ payload−severity ∪ snapshot ∪ `_severity_measures` 派生量）9/9 通过，落在 `engine_check`
- [x] 1.3 判级对数据敏感且确定：用 `_severity(sig, snap)` 直接注入（`streak_below` 加大 / `east_orders.delta_pct` 逼近阈值）断言 `score` 变化方向正确；同一数据源两次 `run_engine()` 的 `severity` 完全相同 → 验证：`python3 -c` 断言两次结果相等 + 注入用例断言 `score` 单调 → 实测：`_severity(p1_sig, {margin.streak_below:6})` → `79 ≥ 76`；`c1` 注入 `east.delta_pct ∈ {-2.9,-1.5,-0.5}` → `scores = [37,34,31]`（离阈值越远越低）；两次 `run_engine()` 的 9 条 `severity` 全等（`engine_check` 内断言）
- [x] 1.4 `tests/engine_check.py` 新增结构性断言（每条洞察含 `severity`、`level ∈ {high,medium,low}`、`score ∈ [0,100]`、`basis=='engine'`、`c1.level` 不高于 `e2.level`），且既有断言与 `pulse 3/2/4/4` 不变 → 验证：`python3 -m tests.engine_check` 输出 `engine self-check OK` 且 pulse 行不变 → 实测：`engine self-check OK` + `pulse = {'problems': 3, 'opportunities': 2, 'changes': 4, 'watching': 4, 'last_updated': '09:32'}`；新增断言含：键集/level 集合/score int∈[0,100]/basis/rule 非空/drivers≥1(name+value)、9 条分布表、`c1(37) ≤ e2(66，以 `{**c1_sig, insight:'e2', type:'problem'}` + `east.delta_pct=-3.4` 注入同快照构造)`、敏感性单调、两次运行全等

## 2. 引擎：可能后果（consequence）

- [x] 2.1 `app/engine/engine.py` 新增纯函数 `_consequence(sig, snap)`（10 个洞察分支 + 证据不足的定性分支，见 design D2）并在 `build_insights()` 下发 `consequence` → 验证：`python3 -c "from app.engine.engine import run_engine; ins=run_engine()['insights']; assert len(ins)==9; assert all(x['consequence']['summary'] and x['consequence']['horizon'] and x['consequence']['condition'] and x['consequence']['impacts'] and x['consequence']['basis']=='engine' for x in ins); print(ins[0]['consequence'])"` → 实测：9 条全含 5 键；p1 = `{summary: 若不干预，利润率将延续 5.4% 的偏离幅度（当前 18.1%，目标 18.5%），成本端压力继续放大, horizon: 4 天, condition: 若成本端未干预, impacts: [目标线 18.5% / 当前利润率 18.1% / 受影响供应商 1 家], basis: engine}`；`summary` 一律以「若…」开头（design 风险缓解 4）
- [x] 2.2 后果数字可回溯（数字锁）：`summary` 与 `impacts[*].value` 中的数字均可在该洞察的 `metric/delta/desc/semantics/severity` 或快照派生值中找到 → 验证：断言脚本对 9 条逐条比对，输出未回溯数字列表为空 → 实测：脚本（payload ∪ snapshot ∪ `_severity_measures` 派生量）→ `未回溯数字 = []`；同名断言已进 `engine_check`（含逗号归一，使 `¥2,985`/`2,460` 与快照 `2985`/`2460` 对齐）
- [x] 2.3 证据不足不臆造：`c2`（数据更新事件）无趋势字段 → `summary` 为定性表述、`impacts` 只含 `受影响指标` 计数（`len(data_event.metrics)`），不含快照外新数字 → 验证：断言 `c2.consequence.summary` 命中「不构成经营后果」且 `impacts` 长度 1 → 实测：`c2.consequence = {summary: 数据事件本身不构成经营后果；重算后若指标触发阈值，将生成对应洞察, horizon: 下次更新前, condition: 若重算结果触发阈值, impacts: [ {受影响指标, 4 项} ]}`（summary 无任何数字；`horizon` 用「下次更新前」而非数字窗口，避免无来源数字）
- [x] 2.4 外推确定性：同一数据源两次 `run_engine()` 的 `consequence` 完全相同 → 验证：`python3 -c` 断言 `[x['consequence'] for x in run_engine()['insights']] == [x['consequence'] for x in run_engine()['insights']]` → 实测：9 条全等（`engine_check` 与 `severity` 一并断言）

## 3. Dora Chat：「后果」意图

- [x] 3.1 `app/routers.py` 的 `CHAT_INTENT_RULES` 新增 `consequence`（关键词：后果/不处理/会怎样/风险/影响面），`_compose_answer` 新增分支输出 `严重等级：…` 与 `可能后果：…` 两段（内容分别取自该洞察 `severity`/`consequence`） → 验证：`curl -s --noproxy '*' -X POST localhost:8000/api/dora/chat -H 'Content-Type: application/json' -d '{"question":"这条洞察不处理会怎样？","insight_id":"p1"}'` 的 `intent=consequence` 且 answer 含两段前缀 → 实测：`intent=consequence`；answer = `严重等级：高 76 分 · 偏离目标 5.4%、距目标线 已越线、连续低于目标 4 天、受影响供应商 1 家、归因因素 2 项` + `可能后果：若不干预，利润率将延续 5.4% 的偏离幅度（当前 18.1%，目标 18.5%），成本端压力继续放大（若成本端未干预；观察窗口 4 天）` + 既有 `下一步建议：`/先例句（段落结构不变）；**关键词顺序**：`consequence` 必须排在 `handle` 之前（「不处理」含「处理」子串）
- [x] 3.2 既有意图回归：`为什么…` → `why`、`证据/依据…` → `evidence`，answer 结构与本轮之前一致（不新增/不丢失段落） → 验证：两问 curl 对比 `intent` 与 answer 行数 → 实测：`为什么利润率会失速？`→`why`、`证据是什么？`→`evidence`、`怎么处理这个洞察？`→`handle`；why answer 仍为 4 行（结论/主要影响因素/下一步建议/先例）；`agent_check` 第 4 节新增断言 `可回溯证据：` 段仍在
- [x] 3.3 数字锁继续成立：`consequence` 意图下 answer 中数字 ⊆ 该洞察引擎 payload → 验证：脚本提取 answer 数字并与 payload 比对，未回溯列表为空 → 实测：answer 数字 `{18.1, 18.5, 1, 2, 4, 5.4, 76}` ⊆ p1 payload（`severity`/`consequence` 本身在 payload 内，故两段文本天然可回溯）→ `未回溯数字 = []`；`agent_check` 第 4 节同断言通过
- 说明（超出 tasks 原文的加固）：把 3.1–3.3 的验收从「一次性 curl」固化为 `tests/agent_check.py` 第 4 节断言（后果两段 + 既有意图不回归 + 数字锁），使 chat 契约变化在 `run_all` 里自动被守


## 4. 前端：判断列三段式

- [x] 4.1 `frontend/src/types.ts` 新增 `InsightSeverity` / `InsightConsequence` 类型，`Insight.severity?` / `Insight.consequence?` 为可选（缺字段不渲染空壳） → 验证：`cd frontend && npx tsc -b` 通过 + `npm run build` 绿 → 实测：`npx tsc -b` exit=0；`npm run build` → `✓ 48 modules transformed` / `✓ built in 537ms`（`dist/assets/index-CC-4cJP5.{css,js}`）
- [x] 4.2 `InsightPage.tsx` 段①：等级徽章（`level` 文案 + `score` + `rule` + `drivers` chips），置于判断列顶部；无 `severity` 时不渲染该段 → 验证：CDP 读 `.judge-col.verdict` 文本含「严重等级」与 `drivers` → 实测：CDP → `严重等级 高 76/100 引擎启发式 · 问题：偏离目标 5.4%、距目标线 已越线、连续低于目标 4 天、受影响供应商 1 家、归因因素 2 项` + `.sev-chip` 5 个（三 tab：problem 高 76/100 chips 5、opportunity 中 59/100 chips 3、change 低 37/100 chips 4）
- [x] 4.3 `InsightPage.tsx` 段③：可能后果块（`summary` + `condition`/`horizon` + `impacts` 列表），置于置信度之上；无 `consequence` 时不渲染该段 → 验证：CDP 读判定列文本含「可能后果」与 `summary` 首句 → 实测：CDP → `可能后果 若成本端未干预 · 窗口 4 天 / 若不干预，利润率将延续 5.4% 的偏离幅度（当前 18.1%，目标 18.5%），成本端压力继续放大` + `.consq-chip` 3 个
- [x] 4.4 `belongsElsewhere` 前缀表加入 `/^严重等级[：:]/`、`/^可能后果[：:]/`（chat 侧同名段落归位到段①/段③） → 验证：CDP 展开「补充说明」后判断列 `ownRest` 不含这两类行（去复述断言沿用迭代 43 脚本） → 实测：三 tab + 展开态 `dup = {"next":false,"ref":false,"cause":false,"sevLine":false,"consqLine":false}`
- [x] 4.5 `styles.css` 增加徽章/后果样式，保持两栏等高 + 置信度贴底（`.verdict-conf{margin-top:auto}`） → 验证：CDP 量两栏 `getBoundingClientRect()` 高度相等 + 置信度块底部对齐卡片底 → 实测：三 tab 两栏 `[{w:496,h:428},{w:496,h:428}]` / `[{w:496,h:342},{w:496,h:342}]` / `[{w:496,h:383},{w:496,h:383}]` 等高；`confGap = 13` = 卡片 `padding-bottom 12 + border 1`（即贴齐内容盒底部；**断言基准应是该内边距，不能按 0 断言**，见 D040 apply 期修订 5）
- [x] 4.6 判断列在 AI 不可用时仍有三段中的段①/段③（等级/后果来自引擎字段）：CDP `Fetch.failRequest` 拦截 `/api/dora/chat` → 段②降级为引擎语义 + 兜底 note，段①/段③不受影响 → 验证：离线脚本断言三段仍在 → 实测：拦截后 段① `badge=高 chips=5` 仍在、段③ summary 照旧、`note = AI 暂不可用，以上为引擎语义兜底`、lead = 引擎 semantics 兜底句

## 5. 离线镜像（`frontend/src/data.ts`）

- [x] 5.1 9 条镜像按引擎同口径补 `severity`/`consequence`，并加注释标注来源（镜像自引擎输出，口径变化需同步） → 验证：`grep -c "severity" frontend/src/data.ts` ≥ 9 且注释存在 → 实测：`grep -c severity` = 12、`grep -c consequence` = 13；实现形态为「`engineJudgment` 常量表（9 条，含每个 id 的 severity + consequence）+ 挂载循环」，注释写明「镜像自迭代 46 引擎输出（`SEVERITY_WEIGHTS` / `_consequence`）；引擎口径变化时必须同步本表；镜像其余数值（metric/delta/desc）仍是更早的演示快照」
- [x] 5.2 镜像与引擎同名同值：脚本比对镜像 9 条与 `run_engine()` 的 `severity.level/score` 与 `consequence.summary` → 验证：比对脚本输出 0 处不一致 → 实测：`./node_modules/.bin/esbuild src/data.ts --bundle --format=esm --outfile=/tmp/dora_data.mjs` + `node /tmp/compare_judgment.mjs` → `镜像 9 条 / 引擎 9 条；不一致 0 处`（首轮抓到 o2 summary 一处空格差异 → 顺手统一引擎文案为 `{region}高客单集群`，消除「华东 高客单」断句）

## 6. 门禁、文档与归档

- [x] 6.1 `cd frontend && npm run build` 绿（tsc -b + vite），无新增根目录产物（`vite.config.js`/`*.tsbuildinfo`） → 验证：构建输出 + `git status --short` 无未跟踪构建产物 → 实测：`✓ built in 537ms`；`git status --short` 恰好 9 个源文件改动（backend 5：`engine.py`/`routers.py`/`schemas.py`/`engine_check.py`/`agent_check.py`；frontend 4：`types.ts`/`InsightPage.tsx`/`styles.css`/`data.ts`），无 `vite.config.js`/`*.tsbuildinfo`/`dist`
- [x] 6.2 `cd backend && python3 -m tests.engine_check` 通过 + `python3 -m tests.run_all` **ALL GREEN**（8 段；golden 9 不变） → 验证：贴 `run_all: ALL GREEN` 与 golden 行 → 实测：`engine self-check OK`；`python3 -m tests.run_all` → `run_all: ALL GREEN`（engine/ingest/reasoning/golden/e2e/watch/action/agent 8 段全 OK）+ `golden_check OK (9 insights matched baseline)`
- [x] 6.3 CDP 主验证（三段齐全、无复述、两栏等高、抽屉/图表回归不破） → 验证：新脚本 `dora_judge3_verify.mjs` 全 PASS + 截图 → 实测：`CDP_PORT=9222 node /tmp/dora_judge3_verify.mjs` → **22/22 PASS**（三 tab × 段①/段③/去复述/两栏等高+贴底/图表 `xMidYMid meet`，抽屉 `46 ↔ 300`，视口 1440/1024/390 `overflow=0`，离线 AI 不可用三段仍在）；截图 `/tmp/dora_shots3/judge3_panel.png`(1070×708) / `judge3_cols.png`(1032×456) / `judge3_offline.png`(1032×480)
- [x] 6.4 端点 curl（绕代理）：`GET /api/insights` 含 `severity`/`consequence`；`GET /api/insights/p1` 同上 → 验证：curl 输出字段清单 → 实测：`/api/insights?type=problem` 每条含 `severity{basis,drivers,level,rule,score}` + `consequence{basis,condition,horizon,impacts,summary}`；`/api/insights/p1` 键集 = 既有 16 键 + `severity`/`consequence`（**apply 期发现**：该端点返回 `InsightSummary`（字段白名单）→ 必须同步扩 `schemas.py`，否则静默丢字段）
- [x] 6.5 文档同步：`docs/持续优化路线.md` 勾选本项（附验证摘要）、`docs/开发过程记录.md` 追加「迭代 44」、`docs/开发问题与经验.md` 记 D 系列（判级权重口径 + 后果外推的取舍与退出条件） → 验证：`python3 -m tests.check_docs` ALL GREEN → 实测：持续优化路线 §2 本项 `[x]`（含归档路径 + 全部验证命令 + 新登记「离线镜像数值与引擎口径同步」候选）；版本路线图「当前打开的工作」改为 `action-step-expert-assign`；开发过程记录追加「**迭代 46**」（N 按归档时实际序号：44/45 已被 `action-loop-timeline`/`watch-delegate-flow` 占用，任务书原写的「迭代 44」为 propose 期占位 → 已纠正）；开发问题与经验 D040 → **已生效** + 5 条 apply 期修订、新增 **P016**；`check_docs` → `ALL GREEN`
- [x] 6.6 `openspec validate insight-judgment-structure --strict` 通过后归档（归档信息含【测试证据】【反思】） → 验证：`openspec validate` 输出 + 归档目录存在 → 实测：`openspec validate insight-judgment-structure --strict` → valid；spec 增量（`business-engine` ×2 + `business-agent` ×1，均为 ADDED）合入 `openspec/specs/`，`openspec validate --specs` → `Totals: 7 passed, 0 failed`；`openspec archive insight-judgment-structure` → `2026-09-11-insight-judgment-structure`；tasks **25/25**

## 测试证据（归档）

- 后端：`python3 -m tests.engine_check` → `engine self-check OK`（新增 severity/consequence 契约、数字锁回溯、等级分布、`c1 ≤ e2` 注入对照、敏感性、确定性）；`python3 -m tests.agent_check` → `[4] dora/chat OK（5 类事件 + run 落库 + 数字锁 + 后果意图两段）`；`python3 -m tests.run_all` → **ALL GREEN**（8 段，`golden 9` 不变）；curl：`/api/insights` 与 `/api/insights/p1` 均含两新字段、`/api/dora/chat` 后果一问 `intent=consequence`
- 前端：`npx tsc -b` exit=0；`npm run build` → `✓ 48 modules transformed / ✓ built in 537ms`；镜像一致性脚本 → `镜像 9 条 / 引擎 9 条；不一致 0 处`
- 端到端（CDP，headless Chrome + `Runtime.evaluate`）：`/tmp/dora_judge3_verify.mjs` → **22/22 PASS**；截图 `judge3_panel.png` / `judge3_cols.png` / `judge3_offline.png`
- 文档/spec：`python3 -m tests.check_docs` ALL GREEN；`openspec validate insight-judgment-structure --strict` valid；`openspec validate --specs` 7 passed

## 反思（归档）

1. **验收命令是「会执行的假设」，必须在 propose 期跑一遍**：本轮 3 条命令里 2 条与实况不符——① `i['e2']` 在当前种子下不存在（`c1`/`e2` 是互斥分支，design 与 tasks 各写了一次）；② `/api/insights/{id}` 走 `InsightSummary` 字段白名单，不扩 `schemas.py` 就会静默丢新字段。教训固化为 P016：**互斥分支不能并列断言**，用注入式断言（`_severity({**sig, insight:'e2'}, 注入快照)`）覆盖「数据变化下才成立」的那一支。
2. **判级「可解释」比「精确」更重要**：`SEVERITY_WEIGHTS` 一处分档 + `drivers` 把依据摊在卡片上，任何「为什么是 76 不是 80」都能逐项对账（`rule` 文案自陈「引擎启发式」）；代价是启发式而非财务口径 —— 这是**有意**的取舍（D040 退出条件 ①：要做行业可配置就把权重提到规则参数）。
3. **数字锁要能自动守**：把「后果/判级的数字 ⊆ payload ∪ 快照派生量」写成 `engine_check` 断言，并让派生量由 `_severity_measures` 显式返回——文本数字只能来自 measures，硬编码数字必被抓（drivers 断言刻意排除 `severity` 自身，避免自证）。
4. **诚实性的边界要写进注释而不是靠记忆**：离线镜像是更早的演示快照，本轮按 design D4 只补 `severity/consequence`（离线/在线判级一致优先），造成离线卡片可能同时出现两套数字 —— 已把「镜像其余数值不同步」写进 `data.ts` 注释、D040 apply 期修订与 backlog 候选，避免下一轮把它当 bug 重复讨论。
5. **验证脚本的断言基准要取计算值而非直觉值**：「置信度贴底」按 `confGap == 0` 断言会得到 3 个假红，实际 `13px` = 卡片 `padding-bottom 12 + border 1`（正确写法是拿 `getComputedStyle` 的 padding+border 做基准）——与 P013「必须量像素」同族：**量了还要量对基准**。


