## 1. 后端：委托卡片回显生命周期字段

- [ ] 1.1 `backend/app/routers.py::_watch_card` 增量 3 个 camelCase 字段：`intent`（解析结果原样）、`lastCheckedAt`（`target["last_checked_at"]`）、`lastEvent`（复用函数内已取的 `last`：`{kind, summary, triggeredAt}` 或 `None`）；不新增查询、不改既有字段 → 验证：`curl -s --noproxy '*' localhost:8000/api/watch | python3 -m json.tool` 每条含三键，且 `python3 -c "...assert set(['intent','lastCheckedAt','lastEvent']) <= set(cards[0])"`
- [ ] 1.2 `backend/tests/watch_check.py` 第 4 节补卡片断言：创建后卡片 `intent.metric_key=='east_orders'` 且 `lastCheckedAt` 非空、`lastEvent.kind=='change'` 且 `summary` 非空；上传跌破后 `lastEvent.kind=='escalate'` 且 `summary` 引用引擎判定；无命中委托（注入一条不命中序列的目标）`lastEvent is None` → 验证：`cd backend && python3 -m tests.watch_check` 输出 `watch_check OK`
- [ ] 1.3 兼容回归（既有字段语义不变）：`name/value/color/logic/source/status/frequency/lastEventAt` 取值与改动前一致 → 验证：`cd backend && python3 -m tests.e2e_api_check` + `python3 -m tests.run_all` 全绿；CDP 脉搏页监控卡行数与文案不变

## 2. 前端：流程派生纯函数

- [ ] 2.1 `frontend/src/types.ts` 新增 `WatchEventCard { kind: 'change'|'escalate'; summary: string; triggeredAt: string }`，`WatchTargetCard` 增 `intent?: WatchParseIntent`、`lastCheckedAt?: string`、`lastEvent?: WatchEventCard | null`（全部可选，缺字段按「未命中」渲染） → 验证：`cd frontend && npx tsc -b` 通过
- [ ] 2.2 新建 `frontend/src/features/watch/delegateFlow.ts`：`buildDelegateFlow({ intent, target, online })` 返回 `{ state, stateLabel, steps: [{n,title,desc,state,note}], hint }`，步骤语义按 design D3（4 步标题沿用现有文案） → 验证：`cd frontend && npx esbuild src/features/watch/delegateFlow.ts --bundle --format=esm --outfile=/tmp/flow.mjs` 后用 node 断言（同 `pulseView.ts` 既有自检法）
- [ ] 2.3 七态断言：① 无 intent 且无 target → 4 步全 `pending` 且 `stateLabel` 含「待命」；② 仅 intent（未创建）→ 步骤 1/2 `done`（note 含 label/dimension/condition 与 `metric_key`）、3/4 `pending`；③ `watching` + `lastCheckedAt` → 步骤 3 `active`（note 含真实频率与时刻）；④ `lastEvent.kind='change'` → 步骤 4 `done` 且 note 含事件 `summary`；⑤ `kind='escalate'` → `stateLabel` 含「已升级」且步骤 4 note 引用引擎判定文案；⑥ `paused` → 步骤 3 `paused`、步骤 4 `pending`；⑦ `online=false` → 步骤 3/4 强制 `pending` 且 `hint` 含「连接后端」 → 验证：node 断言输出 7/7 PASS

## 3. 前端：面板接线与离线标识

- [ ] 3.1 `WatchPage.tsx` 用 `buildDelegateFlow` 渲染右侧面板（保留 4 步标题骨架与「自动完成」Tag，新增头部状态 pill） → 验证：CDP 读 `.delegate-side` 文本含「待命」初始态与 4 步标题
- [ ] 3.2 「当前委托」规则（本会话 `intent`/`focusId` 优先，否则 `targets[0]` 并标注「最近委托」）+ 20s 轮询更新后步骤态同步 → 验证：CDP 依次执行「让 Dora 理解」→「开始持续关注」，面板步骤 1/2 `done`、步骤 3 变 `active` 且 note 含真实频率；等一次轮询后仍一致
- [ ] 3.3 离线降级：`load()` 回退演示数据时置 `offline` → 页头出现「离线演示」Tag、面板步骤 3/4 显式「需连接后端」、不出现「持续检查中/已命中」 → 验证：CDP `Fetch.failRequest` 拦截 `/api/watch*` → 断言三处文本
- [ ] 3.4 交互回归：让 Dora 理解 / 常用目标 / 开始持续关注 / 检查 / 暂停恢复 / 删除 的行为与提示文案与本轮之前一致（不因面板改动引入新请求或新状态） → 验证：CDP 用例覆盖 6 个动作 + 暂停后面板步骤 3 变 `paused`、恢复后回 `active`

## 4. 前端：表格操作列加宽（三按钮同排）

- [ ] 4.1 `styles.css`：`.whead,.wrow` 第 4 列 `0.45fr` → `208px`；`.wopts` 增 `flex-wrap:nowrap;justify-self:end`；`.rowbtn` 增 `white-space:nowrap` → 验证：CDP 量 `.wopts` 三按钮 `getBoundingClientRect().top` 相同（同一行）且 `.wopts` 高度 = 单行按钮高度
- [ ] 4.2 移动端断点（≤760px）：`.wopts{grid-column:1/-1;justify-self:start}`，操作区独占一行且按钮不被压缩 → 验证：CDP 视口 390×844 断言三按钮同排、`.watch-table` `scrollWidth <= clientWidth + 1`
- [ ] 4.3 无横向溢出：1280 / 1024 / 760 三视口 `.watch-table` 与 `body` 均无横向滚动，`.wlogic` 允许换行但不溢出 → 验证：CDP 三视口断言 + 截图

## 5. 门禁、文档与归档

- [ ] 5.1 后端门禁：`cd backend && python3 -m tests.watch_check` + `python3 -m tests.run_all` **ALL GREEN**（8 段；golden 9 不变） → 验证：贴 `run_all: ALL GREEN` 与 golden 行
- [ ] 5.2 前端门禁：`cd frontend && npm run build` 绿；`git status --short` 无构建产物（`vite.config.js`/`*.tsbuildinfo`） → 验证：构建输出 + `git status`
- [ ] 5.3 文档同步：`docs/持续优化路线.md` 本项勾 [x]（附验证/归档路径）、`docs/版本路线图.md`「当前打开的工作」更新、`docs/开发过程记录.md` 追加「迭代 N」（N 按归档时实际序号：44 已用，`insight-judgment-structure` 待 apply 可能先占 45）、`docs/开发问题与经验.md` D042 状态改「已生效」+ 补 apply 期修订 → 验证：`cd backend && python3 -m tests.check_docs` ALL GREEN
- [ ] 5.4 归档：spec delta 先同步进 `openspec/specs/business-watch/spec.md`（需求来源表补 1 行 + 1 条 MODIFIED 全文替换）→ `openspec validate --specs` 全绿 → `openspec archive watch-delegate-flow`，提交信息含【测试证据】+【反思】 → 验证：`openspec validate` 输出 + 归档目录存在（`openspec/changes/archive/<date>-watch-delegate-flow`）
