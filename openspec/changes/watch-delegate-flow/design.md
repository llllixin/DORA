## Context

现状（2026-09-11 读码）：

- `frontend/src/features/watch/WatchPage.tsx` 右侧 `.card.delegate-side` 的面板内容是**内联写死的 4 步数组**（`[['1','理解目标',...], ...]`），与任何状态无关。
- 后端 `app/routers.py::_watch_card` 已把 `WatchTarget` 渲染成 Pulse 兼容卡片：`id/name/value/color/logic/source/status/frequency/lastEventAt`；函数内部**已经取出** `events` 与 `last`（用于算 `value` 的「已暂停/已升级/有变化/观察中」），但只透了 `lastEventAt`，没有结构化 `intent` 与命中事件内容。
- 因此前端要展示「委托走到哪一步」，今天只能靠**字符串嗅探**（从 `logic`/`source` 里切条件文案、从 `value` 里猜 `已升级`）——这正是 D003/D004 要避免的做法。

面板 4 步 × 字段盘点（design D3 的表，勿删）：

| 步骤 | 所需字段 | 在线来源 | 离线兜底 |
|---|---|---|---|
| 1 理解目标 | `intent.label/dimension/condition/frequency` | 会话 `parseWatch` 结果，或卡片 `intent` | 会话 parse 结果（demo 词典） |
| 2 匹配数据口径 | `intent.metric_key` | 同上（解析器词典 = 引擎受支持 metric key） | 同上 |
| 3 持续检查 | `status`/`frequency`/`lastCheckedAt` | 卡片 | 显式「需连接后端」（不伪造） |
| 4 回到业务脉络 | `lastEvent.kind/summary` | 卡片 | 显式「需连接后端」（不伪造） |

## Goals / Non-Goals

**Goals**：面板每一步的态与「当前委托」的真实状态一一对应；表格三按钮同排不折行；离线路径不出现未发生的状态。

**Non-Goals**：不改 `WatchTarget`/`WatchEvent` 模型、解析器、评估器与调度；不新增端点、不做 SSE 推送；不改 `GET /api/watch/{id}`（raw snake_case 详情）；不改表格列语义与操作按钮功能/文案；不把操作列做成图标或下拉菜单。

## Decisions

### D1 用「卡片增量字段」而不是「消费详情端点 / 新端点」

`GET /api/watch/{id}` 返回的是 raw dict（`target` snake_case + `events` snake_case），消费它会引入 snake↔camel 适配层（违 D004），且列表页要为每条委托再打一次请求。改为在 `_watch_card` 上追加 3 个 **camelCase 纯增量字段**（`intent`/`lastCheckedAt`/`lastEvent`）：该函数内 `events`/`last` 已算好，**零新增查询**；列表已在 20s 轮询里，步骤态自然跟上。

- 代价：卡片体略胖（约 +150 字节/条）。
- 退出条件：卡片被别的页面当详情用（字段继续膨胀）→ 拆出 `GET /api/watch/summary` 之类的瘦端点，卡片回归窄形态。

### D2 步骤态由数据推导，派生逻辑抽纯函数

`frontend/src/features/watch/delegateFlow.ts` 导出 `buildDelegateFlow({ intent, target, online })` → `{ state, stateLabel, steps: [{ n, title, desc, state: 'pending'|'done'|'active'|'paused', note }], hint }`。组件只做渲染，派生逻辑可单测——沿用 `features/pulse/pulseView.ts` 先例（frontend-loop-pulse）。

### D3 步骤语义映射（沿用现有 4 个标题，不改骨架）

- 步骤 1/2：由 `intent` 驱动（会话 parse 优先，其次卡片 `intent`）。步骤 2 完成的条件 = 解析成功，理由是解析器 `TARGETS` 词典就是引擎受支持 metric key（不支持的指标在 parse 阶段已被显式拒绝，`/watch/parse` + `POST /watch` 400），因此「匹配引擎口径」不是新判断，而是把已成立的解析结果显式化（`note` 里展示 `metric_key` 与维度）。
- 步骤 3：`status==='watching'` → `active`（`note` = 频率 + 最近检查时刻）；`status==='paused'` → `paused`（`note` = 已暂停 · 不评估）；无委托 → `pending`（note = 确认「开始持续关注」后生效）。
- 步骤 4：`lastEvent===null` → `active`（观察中，尚未命中）；`kind==='change'` → `done`（note = 事件 `summary`）；`kind==='escalate'` → `done`（note = 事件 `summary`，其文本由评估器写入并引用引擎判定）。
- 头部状态 pill 与步骤态同源推导（待命 / 已理解待确认 / 持续关注中 / 已暂停 / 已命中变化 / 已升级），避免「pill 说 A、步骤说 B」。

### D4 面板跟随「当前委托」

本会话刚理解/创建的委托优先（`intent` 在会话态 + `focusId` 指向创建返回的卡片）；否则取列表最新一条（`_watch_card` 列表按 `created_at desc` 排序，取 `targets[0]`）并标注「最近委托」。不引入「点击列表行切换面板」的新交互（用户没要求，且表格行已有三个操作按钮，再加选中态会与「检查」按钮语义打架）。

### D5 离线不伪造

`load()` 落到 `catch`（回退 `data.ts` 镜像）即 `offline=true`：面板只推进步骤 1/2，步骤 3/4 `pending` + `hint`「离线演示：持续检查与命中状态需连接后端」；页头加 `Tag tone="ai"` 「离线演示」（Pulse/Action 先例）。`data.ts` 镜像**不加** `status`/`lastEvent`——一旦镜像带状态就出现「引擎镜像 vs 真实委托」双源（同 D041 决策 7/P013 精神）。

- 退出条件：镜像补齐 `status`/`lastEvent` 并与后端做同值断言后，可放开离线步骤 3/4。

### D6 操作列固定宽度而非继续用比例

`.whead,.wrow` 第 4 列 `0.45fr` → `208px`（三个 `rowbtn` 按当前 `padding:8px 10px` + `font-size:12px` 实测需 ~190px，留余量）；`.wopts` 加 `flex-wrap:nowrap;justify-self:end`，`.rowbtn` 加 `white-space:nowrap`；`@media(max-width:760px)` 下 `.wopts` 显式 `grid-column:1/-1;justify-self:start`（操作区独占一行）。比例列会随容器宽度变化，只有固定宽能保证「三按钮永远同排」。

- 代价：1024–760px 之间「关注逻辑」列会被压窄（文案换行，不溢出）。
- 退出条件：若实测中文换行观感差 → 降到 `200px` 并收紧 `rowbtn` 内边距，或把「删除」收进更多菜单（需另立 change）。

## Risks / Trade-offs

- 卡片增量字段被 Pulse 监控卡/其它消费方误用 → 本次只断言既有字段不变 + Pulse 冒烟。
- 面板状态与表格 `value` 标签可能同时出现（一个说「已升级」一个说「观察中」）→ 两者同源（都来自 `_watch_card` 同一次计算），断言一致性即可。
- 固定 208px 在窄桌面下挤压逻辑列 → CDP 三视口断言无横向滚动。

## Migration Plan

无 DB 迁移、无破坏性变更。前端对新增字段全部按**可选**处理（`?`），字段缺失时按 `lastEvent=null`（观察中）渲染，因此旧后端 + 新前端仍可用（只是步骤 4 停在「观察中」）。

## Verification Plan

- 后端：`cd backend && python3 -m tests.watch_check`（第 4 节补卡片字段断言）→ `python3 -m tests.run_all` ALL GREEN（golden 9 不变）。
- 前端：`cd frontend && npm run build`；`delegateFlow` 用 esbuild 打包后在 node 里断言 6 种态（无委托 / 已理解未创建 / 持续检查 / 命中 / 升级 / 暂停 / 离线）。
- 端到端：CDP 脚本（在线 6 态 + 表格三按钮同排 + 三视口无溢出 + 离线分支 `Fetch.failRequest`），截图留档。
- 文档一致性：`cd backend && python3 -m tests.check_docs`。
