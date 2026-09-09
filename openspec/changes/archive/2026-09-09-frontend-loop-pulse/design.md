## Context

动机与范围见 proposal.md。技术现状（决定本设计的事实）：

- 前端采用 **D008 原位同步**：`App.syncRemoteData()` 在后端在线时把 `/api/insights`、`/api/watch` 结果 `splice` 进 `data.ts` 的 `insights.*` / `watchItems`；所有页面读同一批数组引用，App 重渲染即显示新数据。后端离线时不刷新（本地演示兜底），`detectApi()` 可探测 `/api/health`。
- `watchItems` 的真实来源是 `/api/watch`（`listWatch` → `apiGet('/watch')`，卡片含 name/value/color/logic/status）；Watch parser 词典已支持 `margin→利润率`（全国口径）等。
- PulsePage 目前问题不在计数（计数随同步已真），而在**文案/子面板仍组件内写死**：`view[p1|p2|p3]` 字典、静态 signal/monitor 数组、跟进本地假卡。
- doraApi 的 `createWatch` 语义：后端在线返回真实 target；后端离线（auto 模式）静默走演示或抛 `unsupported`（margin 文本在离线 demoParse 不受支持会抛错）——消费方必须显式区分，否则就是"静默假成功"。

## Goals / Non-Goals

**Goals:**
- Pulse 页不再出现任何后端未提供的业务数字/判断（组件内写死字典清零，数据只来自 `Insight`/watch 卡片字段或显式模板缺省文案）。
- 产出「所需字段 ↔ 来源端点/同步结构 ↔ 降级文案」盘点并固化（`/api/pulse` 仅返回计数，不作为面板数据源）。
- 离线镜像迁移后，停后端冒烟与改动前 demo 观感一致（删字典 ≠ 空壳）。
- 「让 Dora 帮我跟进」产生**真实** Watch 委托并可取消；不可委托/离线时行为诚实（禁用或明确提示），页面状态与真实委托列表一致。
- 保持 D008 同步架构与现有样式/DOM 结构，零后端改动。

**Non-Goals:**
- Insight 页/图表/框架级（Sidebar/Topbar/EvidenceDrawer）接线、20s 轮询补齐 → §3D.1-W2/W3。
- 全局"离线演示"banner 完整设计 → W3；本 change 仅 Pulse 局部诚实标识。
- AskBar/Followup 追问（F8）、图表引擎驱动（F11）。
- 修改 watch 词典/后端契约（如结构化阈值字段让委托精确复刻 18.5% 引擎触发）——见 Open Questions。

## Decisions

### D1 沿用原位同步持有结构，不新增 /pulse 页面级请求
Pulse summary/主区/信号板/监控卡直接消费已被后端刷新的 `insights.*` 与 `watchItems`（与洞察页、Watch 页同一数据源），**不新增** `/api/pulse` 请求。
- 为什么：`/api/pulse.watching` 语义为 `changes` 计数（engine 内 `counts["watching"] = counts["changes"]`），**不等于**真实 `/api/watch` 委托数，页面"持续关注"卡若读它反而错；消费既有同步数组零额外请求且与列表页天然一致。
- 备选：Pulse 每次挂载拉 `/api/pulse` + `/api/watch` → 数据源与列表页分叉风险 + 重复请求，否决。

### D2 展示派生收敛为纯函数模块 `pulseView.ts`
新增 `frontend/src/features/pulse/pulseView.ts`，导出：
- `heroFor(insight)`：`{copy, facts, fallback}`——copy/facts 只由 `desc`/`semantics.{causeA,causeB}`/`metric`/`delta` 拼接；无 semantics 时返回"模板未覆盖该洞察的可视化归因，以下为引擎原文"类缺省，不编造数值。
- `signalsFrom(o: Insight[], c: Insight[])`：信号板行（type/title/desc/metric/delta），值全取自引擎字段。
- `monitorsFrom(watch: WatchTargetCard[], problems: Insight[])`：监控行（name/status/value/logic 取自真实卡片；problem 触发态可从 `problems` 中同名 metric 派生"已触发问题"标签）。
- `followTargetFor(insight)`：见 D4。
- 为什么：把"真实化逻辑"与组件解耦、可单测；PulsePage 变薄。
- 备选：就地写映射 → 测试性差、W 系列后续复用难，否决。

### D3 移除无后端依据的装饰信息，宁缺勿假
现主区 `target: 目标 18.5%` 等 chip 与"连续 N 天下跌"逻辑没有结构化字段可引用（只在 `desc` 叙述文本里），一律**不**保留为独立事实行；改为展示 `metric`/`delta`/`source` 这些引擎字段。
- 为什么：V3 起红线=数值永不来自前端模板；叙述文本不可被前端二次断言。
- 备选：正则从 desc 抠阈值 → 脆弱且本质仍是前端断言，否决。

### D4 「让 Dora 帮我跟进」= 可委托洞察才出现；离线/不可委托显式诚实
- `followTargetFor(insight)`：仅在洞察的 metric 命中前端维护的**最小别名表**（首版仅 `margin→"利润率"`，全国口径、与 watch parser 词典同义）时返回可解析委托文本 `关注利润率，连续 3 天下跌提醒我`——**实测**该句被显式解析为 `streak_below days=3`、`condition_defaulted=false`（**非** parser 默认条件，措辞与实现一致）；否则返回 `null`。
- PulsePage 行为：可委托 → 按钮点击先 `detectApi()`：在线则 `createWatch(text)`，成功展示**后端返回的真实 target**（name/logic）并提示可到持续关注页管理；失败/离线/不可委托 → 按钮禁用或提示原因（"后端离线，无法真实建档"），**永不**显示伪造跟进卡。
- 已关注态：由 `watchItems` 是否存在同 label（如"利润率"）委托推导；「取消委托」与创建**对称**——先 `detectApi()`，在线才调 `deleteWatch(id)`，离线/失败禁用并显式提示（`deleteWatch` 离线 fallback 返回 `{ok:true}` 是"假 ok"，必须前置拦截，review P1-3）；创建/取消成功后用 `listWatch()`+`replaceList`（或 `syncRemoteData`）刷新 `watchItems`，保持与 Watch 页同源（D008，review P1-4）。
- 为什么：跟进本质是"把当前问题的心智转成可持续检查的委托"，语义上与 `POST /api/watch` 精确对齐；宁可不提供一键也不提供假一键。
- 备选：把所有问题都允许跟进但离线静默落空 → 复现 F 系列"静默成功"，否决。

### D5 最小别名表是唯一受控的前后端重复
跟进按钮需要知道"该 metric 能否被后端 parser 接受"，因此前端需一张 metric→alias 小表（首版 1 条：margin/利润率）。
- 为什么：逐洞察手工 craft 语句无法从后端直接拉词典（无该端点且不引新端点）；重复面收敛到 1 个文件、1 条记录，可随词典演进同步。
- 缓解：apply 期任务 1.1 用 `curl /api/watch/parse` 实测该别名真实可解析后才启用；若运行时解析仍失败，走 D4 的诚实报错而非假成功。

### D6 字段盘点：面板展示字段只映射到有据来源，/api/pulse 不承载面板数据（审查补强 2）
盘点结果（固化进 `pulseView.ts` 头注释）：

| Pulse 面板 | 所需字段 | 来源（后端在线） | 离线兜底 | 降级文案 |
|---|---|---|---|---|
| Summary 计数 | problems/opportunities/changes 数、持续关注数 | `/api/insights`（各 type 长度）+ `/api/watch`（长度）同步结构 | `data.ts` 镜像 | 离线=按镜像计数并显示「离线演示」 |
| 主区优先级卡 | title/desc/confidence/metric/delta/source + semantics{causeA,causeB} | `/api/insights?type=problem`（含 semantics，reasoning 缓存/模板） | `data.ts` 镜像 semantics | 无 semantics →「模板未覆盖该洞察的归因，以下为引擎原文」；只展示 metric/delta/source |
| 信号板 | type/title/desc/metric/delta | `/api/insights?type=opportunity|change` | 镜像 | 空列表→「暂无该类信号」（不编造行） |
| 监控卡 | name/value/color/logic/status | `/api/watch`（`_watch_card` 真实行） | 镜像 watch 行 | 空→「暂无持续关注委托」；镜像行标注离线 |
| 本轮工作 | 数据检查时间/行数、判定计数 | `/api/insights` 计数 + dataLabel | 镜像 | 沿用 dataLabel + 计数 |

**结论**：不消费 `/api/pulse`（engine 内 `watching=changes` 计数语义，非真实委托数，见 D1）；PulsePage 与 `pulseView.ts` 全用 `/api/insights`/`/api/watch` 的同步结构。

### D7 离线镜像迁移：等价演示内容下沉到 data.ts 结构化字段（审查补强 1）
删除组件写死字典的同时，把其等价内容迁移进 `data.ts` 离线镜像，保证 `pulseView` 同一套代码在离线态也有数据可渲染：
- demo 洞察（p1–o2 等）补结构化 `semantics`（causeA/causeB/next，数值与字段口径来自现 demo 文案），`heroFor` 离线输出与改动前观感一致。
- demo `watchItems` 补 `monitorsFrom` 所需字段（如 `status` 缺省 `watching`），离线监控卡正常。
- `data.ts` 顶部注明「离线演示镜像：仅后端不可用时的兜底数据，非实时判断」。
- 为什么：直接删字典会让离线态变空壳，demo 无法演示；下沉为结构化字段避免再次把文案写死在组件。
- 备选：离线态读后端失败就不渲染子面板 → 演示价值归零，否决。

### D8 主区默认焦点不写死 id：derive + clamp + 空态（review P1-2）
删除写死 `view[p.id]` 字典时，主区当前问题默认选中同步从字面量 `'p1'` 改为「`insights.problem[0]?.id`」；引擎问题列表变化（数据更新后 p1 消失/顺序改变）时对选中做 clamp/reset；problem 列表为空渲染显式空态（不白屏）。
- 为什么：Pulse 是引擎判定的表达，问题集是动态的（真实数据可能没有 p1）；写死 id 会导致真实数据集下悬空或白屏。
- 备选：固定展示第一条不做 state → 丢失"问题栈上下滑动"交互；选中失效不做 clamp → 悬空选中，均否决。

## Risks / Trade-offs

- [Pulse 文案观感下降：原 demo 有精心写死的"目标线/供应商B"等细节] → 诚实优先（D3）；真实字段 + 模板缺省足以支撑"总览入口"，细节留给 Insight/Evidence 页。
- [别名小表与后端 parser 词典漂移] → 收敛到最小、任务 1.1 前置 curl 实测 + 运行时失败显式报错兜底（D5）。
- [后端在线但页面停留时数据已过期（无轮询）] → 依赖现有 remount/更新流程（W3 统一补 20s 轮询），本 change 不重复实现。
- [跟进条件未能精确复刻引擎 18.5% 阈值触发，只做显式的"连续 3 天下跌"委托] → 当前引擎洞察未下发结构化阈值；用显式 `streak_below days=3` 委托（`condition_defaulted=false`）表达，不冒充阈值、不在前端断言阈值数值。如需精确复刻需后端补 threshold 字段（见 Open Questions），超出本 change。
- [DOM/样式回归] → 尽量保留结构类名；`npm run build` + 浏览器冒烟验证。
- [离线镜像仍是演示叙事、非实时判断，若被在线态混用会重新引入假数据] → 镜像仅在 `detectApi=false` 时渲染且带「离线演示」标识（任务 3.3/5.3 断言）；在线数据源只认 `/api/insights`+`/api/watch` 同步结构。

## Migration Plan

- 纯前端接线，无后端/DB/数据迁移。
- 发布：改前端 → build → 冒烟；回滚：`git revert` 该 change 的提交即可（后端不动）。
- `data.ts` 演示镜像保留，但 Pulse 组件只在 `detectApi=false`（离线兜底）时呈现它，并打「离线演示」局部标识。

## Open Questions

1. **跟进委托的触发条件**：本 change 用显式委托句 `关注利润率，连续 3 天下跌提醒我`（实测解析为 `streak_below days=3`、`condition_defaulted=false`）作为 `margin` 跟进的委托条件，**不**精确复刻引擎的"连续 3 天低于 18.5%"。若要精确，需后端在洞察上补充结构化阈值字段（新契约、新端点/字段改动，超出本 change，建议另立）。**评审已确认按此默认，如需变更请提出。**
