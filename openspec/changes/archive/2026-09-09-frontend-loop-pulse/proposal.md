## Why

V1–V5 主线（洞察/Action/Watch/Knowledge）已全部接到真实后端，但 **Pulse（业务脉搏总览）页仍是剩余「静态双源」重灾区**：Summary 计数虽随 `syncRemoteData` 更新，主区优先级卡的文案/facts、信号板、监控卡与「本轮 Dora 工作」仍是组件内按 `p1/p2/p3` **写死的演示字典**；「让 Dora 帮我跟进」只改本地 state 并伪造一张 `PRF-0831 · 每日检查供应商 B 价格` 的跟进卡，从不落真实委托。这与"前端只表达后端判断、判断不残留页面"的基线原则冲突，是 2026-09-08 前端接线审计（`docs/持续优化路线.md` §3D.1-W1，含两条审查补强）的收口项。

## What Changes

- **PulsePage 去写死**：删除组件内按 id（p1/p2/p3）写死的 `view` 文案字典、静态 `signal`/`monitor` 数组与伪造"已建立跟进"演示卡。
- **主区/信号板/监控卡真实化**：优先级卡文案与 facts 由该洞察的引擎字段派生（`desc`/`semantics`/`metric`/`delta`，缺 semantics 时显示"模板未覆盖"而非编造）；信号板由 `/api/insights` 的 opportunity+change 真实行生成；监控卡由 `/api/watch` 真实委托列表生成——沿用 D008「原位同步持有结构」（后端在线时即真实数据），不新增网络层。
- **「让 Dora 帮我跟进」接真实 Watch**：对**可委托**的洞察（其 metric 在 watch 词典有全国口径别名，如 `margin`/利润率）生成委托语句并调用既有 `POST /api/watch`；创建成功后展示真实 target（名称/关注逻辑）并支持取消（`DELETE /api/watch/{id}`）；**不可委托或后端离线时显式禁用/提示，绝不伪造本地跟进卡**。
- **字段盘点先行（审查补强 2）**：对主区/信号板/监控卡所需展示字段与现有端点/同步结构做映射盘点并固化（见 design.md D6）；`/api/pulse` 现**仅返回计数**、不携带主区/信号板/监控卡所需字段 → 面板数据来自 `/api/insights`+`/api/watch` 的 D008 同步结构，不新增对 `/api/pulse` 的页面依赖。
- **离线镜像迁移（审查补强 1）**：组件内写死的等价演示内容迁移进 `data.ts` 离线镜像（demo 洞察补结构化 `semantics`、demo watch 行补展示所需字段），验收含「停后端离线冒烟与改动前 demo 观感一致」，杜绝"删字典 = 离线空壳"；`data.ts` 引用处标注「离线演示」。
- 视觉布局基本不动（只改数据与状态来源）；`data.ts` 仅保留「离线演示」兜底；后端契约零改动。

**迁移/兼容说明**：本 change 不改任何后端端点与字段；仅前端展示来源与一个按钮行为变化。旧的"跟进=本地假卡"交互被移除（无数据兼容负担）。

## Capabilities

### New Capabilities
（无。本 change 不引入新能力 spec。）

### Modified Capabilities
（无 spec 需求变化。既有 spec 已覆盖本 change 的契约来源：`business-watch` Requirement 4「Pulse 持续关注计数与最近状态来自真实委托列表」、`business-engine`「洞察/证据由引擎产出、不依赖静态兜底」；本 change 是把 Pulse 前端实现**向既有契约收敛**的前端接线/清理，不改变任何系统对外行为契约 → `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **前端**：`frontend/src/features/pulse/PulsePage.tsx`（重构主区/信号板/监控卡/跟进）；新增 `frontend/src/features/pulse/pulseView.ts`（从 `Insight[]`/watch 卡片派生展示结构的纯函数模块 + 字段盘点表）；`frontend/src/data.ts`（离线镜像迁移：demo 洞察补 semantics、demo watch 行补展示字段，仅供离线兜底）；复用 `services/doraApi.ts` 既有 `createWatch/deleteWatch/listWatch/detectApi`，不改其签名。
- **后端/DB**：无改动（无新端点、无表、无契约变化）。
- **依赖**：无新增。
- **测试/门禁**：`cd backend && python3 -m tests.run_all`（≥7 段 ALL GREEN、golden 9 不变）；`cd frontend && npm run build`；`curl /api/watch/parse|create|list` 冒烟；页面冒烟**双态**（后端在线=真实数据与列表页一致；停后端=与改动前 demo 观感一致 + 明确「离线演示」提示 + 跟进不假建档）。
