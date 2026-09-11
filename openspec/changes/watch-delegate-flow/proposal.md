## Why

持续关注（业务目标委托）页右侧的「Dora 接到委托后会做什么」是 `WatchPage.tsx` 里的**写死四步数组**（理解目标 / 匹配数据口径 / 持续检查 / 回到业务脉络），与左侧真实的委托状态毫无关系：用户输入目标、点「让 Dora 理解」、点「开始持续关注」、委托命中甚至升级之后，这块面板**一字不变**——看不出「我的委托现在走到哪一步、是否真的在检查、有没有命中回脉搏」。而左侧的委托列表与 `GET /api/watch` 卡片其实已经承载了这些事实（`status`/`frequency`/`lastEventAt`/`value`），缺的只是**结构化回显字段**与**由数据驱动的流程**。

同页次要问题：表格「操作」列宽 `0.45fr`（`styles.css` `.whead,.wrow` 栅格第 4 列），放不下「检查 / 暂停(恢复) / 删除」三个 `rowbtn`，实际渲染折行挤压。

## What Changes

- **委托卡片新增 3 个纯增量 camelCase 字段**（`GET /api/watch` 列表项、`POST /api/watch` 与 `PATCH /api/watch/{id}` 的 `target`）：
  - `intent`：解析结果原样回显（`metric_key`/`dimension`/`condition`/`frequency`/`label`/`condition_defaulted`）；
  - `lastCheckedAt`：最近一次评估时刻；
  - `lastEvent`：最近一次命中事件 `{ kind: 'change'|'escalate', summary, triggeredAt }`，无命中为 `null`。
- **右侧面板从静态改为真实状态驱动的流程**（沿用现有 4 个步骤标题，不改文案骨架）：
  - 待命（未理解）→ 步骤 1/2 完成（展示真实指标/范围/条件 + 引擎口径 `metric_key`）→ 步骤 3 进行中（真实频率 + 最近检查时刻；`paused` 时显式「已暂停 · 不评估」）→ 步骤 4 命中变化 / 已升级（`escalate` 文案引用引擎判定，取自事件 `summary`）。
  - 派生逻辑抽到 `features/watch/delegateFlow.ts` 纯函数（沿用 `pulseView.ts` 的「派生与组件解耦、可单测」先例），组件只渲染。
  - 面板跟随「当前委托」：本会话刚理解/创建的优先，否则取列表最新一条并标注「最近委托」；20s 轮询刷新后步骤态同步。
- **离线/演示不伪造**：`load()` 回退 `data.ts` 镜像即视为离线 → 步骤 3/4 显式标注「需连接后端」，步骤 1/2 仍按本地解析结果推进，并在页头加「离线演示」标识（沿用 Pulse/Action 先例）。
- **表格操作列加宽**：`.whead/.wrow` 第 4 列由 `0.45fr` 改为固定 `208px`，`.wopts` 不折行、`.rowbtn` 不换行；移动端断点（≤760px）操作区独占一行。

**BREAKING**：无。卡片新字段为可选增量，既有消费方（Pulse 监控卡、Topbar、表格既有列）读的字段一个不动、语义不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `business-watch`：「委托经 REST 可管理并回显到界面」需求扩展 —— 委托卡片 SHALL 回显解析 `intent`、`lastCheckedAt` 与最近一次命中事件（`lastEvent`），前端 Watch 页 SHALL 用这些真实字段驱动「委托生命周期」流程回显，SHALL NOT 展示与真实委托状态不符的步骤态；离线回退时该流程只推进到本地已知步骤并显式标注。

## Impact

- **后端**：`app/routers.py::_watch_card`（纯增量字段，复用函数内已取的 `events`/`last`，**零新增查询**）；`tests/watch_check.py` 第 4 节补卡片字段断言。
- **前端**：`types.ts`（`WatchEventCard` + `WatchTargetCard` 可选增量字段）、`features/watch/delegateFlow.ts`（新建）、`features/watch/WatchPage.tsx`、`styles.css`。
- **契约**：`GET /api/watch`、`POST /api/watch`、`PATCH /api/watch/{id}` 的 target 卡片增量字段；`GET /api/watch/{id}`（raw snake_case 详情）保持不变；无 DB 迁移。
- **非目标**：不改 Watch 领域模型 / 解析器 / 评估器；不做 SSE 推送（仍为 20s 轻量轮询）；不改表格列语义、不动操作按钮功能与文案；不把操作列改为图标/下拉菜单。
- **文档**：本 change 归档时追加 `docs/开发过程记录.md`「迭代 N」、勾选 `docs/持续优化路线.md` 本项、`docs/开发问题与经验.md` D042（propose 期已记，归档时补 apply 期修订）。
