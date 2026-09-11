## 1. 引擎：洞察严重等级（severity）

- [ ] 1.1 `app/engine/engine.py` 新增 `SEVERITY_WEIGHTS`（base/trend/threshold/duration/impact/attribution 分档与 level 切点，见 design D1）与纯函数 `_severity(sig, snap)`，并在 `build_insights()` 的洞察字典中下发 `severity` → 验证：`cd backend && python3 -c "from app.engine.engine import run_engine; i={x['id']:x for x in run_engine()['insights']}; print([(k, v['severity']['level'], v['severity']['score']) for k, v in i.items()]); assert all('severity' in x for x in i.values()); assert i['p1']['severity']['level']=='high'; assert i['c1']['severity']['level']=='low' and i['e2']['severity']['level']=='medium'; assert i['c1']['severity']['score'] <= i['e2']['severity']['score']"`
- [ ] 1.2 `rule` 与 `drivers` 可读且可回溯：`rule` 非空、`drivers` 至少一项（`{name, value}`），且 `drivers[*].value` 中出现的数字均能在该洞察 payload（`metric/delta/desc/semantics/trigger`）或快照派生值中找到对应 → 验证：逐条断言 + 人工读一遍 `p1` 的 `rule` 文案
- [ ] 1.3 判级对数据敏感且确定：用 `_severity(sig, snap)` 直接注入（`streak_below` 加大 / `east_orders.delta_pct` 逼近阈值）断言 `score` 变化方向正确；同一数据源两次 `run_engine()` 的 `severity` 完全相同 → 验证：`python3 -c` 断言两次结果相等 + 注入用例断言 `score` 单调
- [ ] 1.4 `tests/engine_check.py` 新增结构性断言（每条洞察含 `severity`、`level ∈ {high,medium,low}`、`score ∈ [0,100]`、`basis=='engine'`、`c1.level` 不高于 `e2.level`），且既有断言与 `pulse 3/2/4/4` 不变 → 验证：`python3 -m tests.engine_check` 输出 `engine self-check OK` 且 pulse 行不变

## 2. 引擎：可能后果（consequence）

- [ ] 2.1 `app/engine/engine.py` 新增纯函数 `_consequence(sig, snap)`（10 个洞察分支 + 证据不足的定性分支，见 design D2）并在 `build_insights()` 下发 `consequence` → 验证：`python3 -c "from app.engine.engine import run_engine; ins=run_engine()['insights']; assert len(ins)==9; assert all(x['consequence']['summary'] and x['consequence']['horizon'] and x['consequence']['condition'] and x['consequence']['impacts'] and x['consequence']['basis']=='engine' for x in ins); print(ins[0]['consequence'])"`
- [ ] 2.2 后果数字可回溯（数字锁）：`summary` 与 `impacts[*].value` 中的数字均可在该洞察的 `metric/delta/desc/semantics/severity` 或快照派生值中找到 → 验证：断言脚本对 9 条逐条比对，输出未回溯数字列表为空
- [ ] 2.3 证据不足不臆造：`c2`（数据更新事件）无趋势字段 → `summary` 为定性表述、`impacts` 只含 `受影响指标` 计数（`len(data_event.metrics)`），不含快照外新数字 → 验证：断言 `c2.consequence.summary` 命中「不构成经营后果」且 `impacts` 长度 1
- [ ] 2.4 外推确定性：同一数据源两次 `run_engine()` 的 `consequence` 完全相同 → 验证：`python3 -c` 断言 `[x['consequence'] for x in run_engine()['insights']] == [x['consequence'] for x in run_engine()['insights']]`

## 3. Dora Chat：「后果」意图

- [ ] 3.1 `app/routers.py` 的 `CHAT_INTENT_RULES` 新增 `consequence`（关键词：后果/不处理/会怎样/风险/影响面），`_compose_answer` 新增分支输出 `严重等级：…` 与 `可能后果：…` 两段（内容分别取自该洞察 `severity`/`consequence`）→ 验证：`curl -s --noproxy '*' -X POST localhost:8000/api/dora/chat -H 'Content-Type: application/json' -d '{"question":"这条洞察不处理会怎样？","insight_id":"p1"}'` 的 `intent=consequence` 且 answer 含两段前缀
- [ ] 3.2 既有意图回归：`为什么…` → `why`、`证据/依据…` → `evidence`，answer 结构与本轮之前一致（不新增/不丢失段落） → 验证：两问 curl 对比 `intent` 与 answer 行数
- [ ] 3.3 数字锁继续成立：`consequence` 意图下 answer 中数字 ⊆ 该洞察引擎 payload → 验证：脚本提取 answer 数字并与 payload 比对，未回溯列表为空

## 4. 前端：判断列三段式

- [ ] 4.1 `frontend/src/types.ts` 新增 `InsightSeverity` / `InsightConsequence` 类型，`Insight.severity?` / `Insight.consequence?` 为可选（缺字段不渲染空壳） → 验证：`cd frontend && npx tsc -b` 通过 + `npm run build` 绿
- [ ] 4.2 `InsightPage.tsx` 段①：等级徽章（`level` 文案 + `score` + `rule` + `drivers` chips），置于判断列顶部；无 `severity` 时不渲染该段 → 验证：CDP 读 `.judge-col.verdict` 文本含「严重等级」与 `drivers`
- [ ] 4.3 `InsightPage.tsx` 段③：可能后果块（`summary` + `condition`/`horizon` + `impacts` 列表），置于置信度之上；无 `consequence` 时不渲染该段 → 验证：CDP 读判定列文本含「可能后果」与 `summary` 首句
- [ ] 4.4 `belongsElsewhere` 前缀表加入 `/^严重等级[：:]/`、`/^可能后果[：:]/`（chat 侧同名段落归位到段①/段③）→ 验证：CDP 展开「补充说明」后判断列 `ownRest` 不含这两类行（去复述断言沿用迭代 43 脚本）
- [ ] 4.5 `styles.css` 增加徽章/后果样式，保持两栏等高 + 置信度贴底（`.verdict-conf{margin-top:auto}`）→ 验证：CDP 量两栏 `getBoundingClientRect()` 高度相等 + 置信度块底部对齐卡片底
- [ ] 4.6 判断列在 AI 不可用时仍有三段中的段①/段③（等级/后果来自引擎字段）：CDP `Fetch.failRequest` 拦截 `/api/dora/chat` → 段②降级为引擎语义 + 兜底 note，段①/段③不受影响 → 验证：离线脚本断言三段仍在

## 5. 离线镜像（`frontend/src/data.ts`）

- [ ] 5.1 9 条镜像按引擎同口径补 `severity`/`consequence`，并加注释标注来源（镜像自引擎输出，口径变化需同步） → 验证：`grep -c "severity" frontend/src/data.ts` ≥ 9 且注释存在
- [ ] 5.2 镜像与引擎同名同值：脚本比对镜像 9 条与 `run_engine()` 的 `severity.level/score` 与 `consequence.summary` → 验证：比对脚本输出 0 处不一致

## 6. 门禁、文档与归档

- [ ] 6.1 `cd frontend && npm run build` 绿（tsc -b + vite），无新增根目录产物（`vite.config.js`/`*.tsbuildinfo`） → 验证：构建输出 + `git status --short` 无未跟踪构建产物
- [ ] 6.2 `cd backend && python3 -m tests.engine_check` 通过 + `python3 -m tests.run_all` **ALL GREEN**（8 段；golden 9 不变） → 验证：贴 `run_all: ALL GREEN` 与 golden 行
- [ ] 6.3 CDP 主验证（三段齐全、无复述、两栏等高、抽屉/图表回归不破） → 验证：新脚本 `dora_judge3_verify.mjs` 全 PASS + 截图
- [ ] 6.4 端点 curl（绕代理）：`GET /api/insights` 含 `severity`/`consequence`；`GET /api/insights/p1` 同上 → 验证：curl 输出字段清单
- [ ] 6.5 文档同步：`docs/持续优化路线.md` 勾选本项（附验证摘要）、`docs/开发过程记录.md` 追加「迭代 44」、`docs/开发问题与经验.md` 记 D 系列（判级权重口径 + 后果外推的取舍与退出条件） → 验证：`python3 -m tests.check_docs` ALL GREEN
- [ ] 6.6 `openspec validate insight-judgment-structure --strict` 通过后归档（归档信息含【测试证据】【反思】） → 验证：`openspec validate` 输出 + 归档目录存在
