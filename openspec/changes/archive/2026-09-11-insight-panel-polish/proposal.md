## Why

洞察页「为什么值得处理 / 放大 / 关注」区域（`.detail-bottom.one-col`）的**判断列**此前直接把 `/api/dora/chat`(why) 的整段答案原文当判断展示，而后端 `_compose_answer` 固定拼五段：`结论句 / 主要影响因素 / 进一步定位 / 下一步建议 / 历史先例(或「历史知识库暂无同指标先例」)`。结果是判断列**复述了同一页面的其它区块**——下方独立的「下一步建议」面板（同一批 `semantics.next`）被再念一遍，左栏归因卡（causeA/causeB）与「历史先例」信息被再排一遍。

用户实测（2026-09-11，p1 利润率）：判断列出现「下一步建议：核对供应商 B 最近采购价（¥132.6）与合同口径；…」——「为什么值得处理」本该只回答**为什么**，不该是下一步动作清单。同时，判断列去掉复述后，两栏等高时右卡片留白偏大，需要一次性定版。

本 change 收口「判断列 = 判断本身」这一呈现规则，并定版该区域的等高/留白取舍。

**本轮同批（同一工作树未提交的展示层改动，一并收口）**：洞察页接入 Dora AI 判断（`/api/dora/chat` SSE + 失败/离线降级）、洞察列表改可折叠抽屉、图表等比缩放与纵轴刻度小数位、脉搏页信号板布局与「专家团能力说明」chips、以及支撑以上各项的样式收敛。change id 沿用用户指定名称 `insight-panel-polish`（范围含脉搏页/图表同批展示层改动）。

## What Changes

- **判断列去复述**（`frontend/src/features/insight/InsightPage.tsx`）：新增 `belongsElsewhere` 行归类，判断列**只**显示「判断独占」的行（默认最多 2 行 + 「展开补充说明」），**展开也不带出**已归属别处的行：
  - `主要影响因素 / 主要因素 / 主要贡献 / 当前变化 / 进一步定位：…` → 左栏归因卡（已有）
  - `下一步建议：…` → 下方「下一步建议」面板（已有，同一批 `semantics.next`）
  - `可参考历史先例：… / 历史知识库暂无同指标先例。` → 左栏「历史先例」行
- **左栏新增「历史先例」行**：chat 检索命中时显示 `先例标题（code）`；检索确实为空时显示「暂无同指标先例」（`ev-none` 次要色）；AI/chat 不可用（`judge.err`）时**不显示**该行（不把「查不到」伪造成判断依据）。
- **布局定版**：两栏保持**等宽等高**（既有 `align-items:stretch`），置信度贴卡片底（`.verdict-conf{margin-top:auto}`）；新增 `.ev-row span.ev-none` 次要色。
- **注释同步**：代码头「字段盘点表」补「判断列」来源行，并固化「判断列不重复其它区块」规则（含示例原文）。
- **洞察页接入 Dora AI 判断**（同批）：新增 `frontend/src/services/doraApi.ts::askDora(question, {insightId, page})`——SSE 逐事件解析 `thought_step / tool_call / evidence / answer / done`，20s 超时 + `AbortController`；`InsightPage` 用它取「为什么值得处理 / 放大 / 关注？」的 AI 判断，三态：loading「正在结合证据判断…」/ 成功（结论句 + 判断独占补充 + 置信度 + 左栏「历史先例」行）/ **失败或离线**（`judge.err` → 引擎 `semantics` 兜底句 + 「AI 暂不可用，以上为引擎语义兜底」note）。
- **洞察页布局**（同批）：洞察列表改为可折叠抽屉（`.insight-drawer`，收起 46px；换洞察时判断列展开态重置）；底部区域改「上=事实/判断两栏卡片，下=下一步建议面板」；归因卡两列并排（`.cause-grid`）。
- **图表等比 + 刻度精度**（同批，`frontend/src/components/charts/InsightChart.tsx`）：5 处 `preserveAspectRatio="none"` → `"xMidYMid meet"`（容器尺寸变化不再拉伸变形，图高恒定）；纵轴刻度按 `tickStep` 决定小数位（`≥1→0 / ≥.1→1 / 否则 2`）并把 `-0` 归一（消除 `20% / 20%` 这类取整重复标签）。
- **脉搏页展示收口**（同批，`frontend/src/features/pulse/PulsePage.tsx`）：「自动编排 · 专家团能力说明」由单行静态文案改为**可点 chips**（切换展示该专家能力说明；数据来自 `data.ts` 的 `capabilities.专家团` + `autoExpertNotes` 离线镜像，**E3 `expert-registry-ui` 落地后换 registry**）；信号板卡片布局（`.signal-*`，数值/变化不换行、按钮右对齐）；移除「持续关注」卡片标题后的「?」提示（`.summary-card .q` 规则注释保留删除说明）。
- **非目标（Out of scope）**：不改后端 `/api/dora/chat` 的意图模板与文案（AskBar 里直接问「为什么…」仍应得到含下一步建议的**完整答案**，这是 chat 的合理行为）；F8 AskBar 追问真实化、F11 图表引擎驱动不夹带；专家团 chips 不在此处接 registry（归 E3）；不触碰判定/数字/置信度（D004 红线，判断列结论句仍逐字来自引擎/chat 原文）。

**迁移/兼容说明**：纯前端展示层收敛，后端与 API 契约零改动，无数据迁移。变化点：洞察判断来自 `/api/dora/chat` SSE（失败/离线自动降级，无后端时仍是引擎语义兜底，不空白）；图表改为等比（容器宽高变化时不再拉伸，图形位置随之居中）；列表抽屉可折叠（仅视图状态，无持久化）。在线态判断列变短（结论句 + 置信度），归因/先例/下一步各回其位，**信息量不减（零丢失，仅去重与换位）**；离线/`judge.err` 兜底态仍走「引擎语义兜底」文案 + `verdict-note` 显式说明，不新增假值。

## Capabilities

### New Capabilities
（无。本 change 是**展示层**收敛：无新能力、无端点、无数据模型。）

### Modified Capabilities
（无 spec 需求变化。判断由引擎产出、`semantics` 由 reasoning 下发、chat 只组装引擎字段——这些既有系统行为由 `business-engine` / `business-agent` 的既有需求覆盖，本 change 不改任何系统对外行为，只改前端对同一批字段的**排布/呈现规则**，故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **前端（5 文件）**：`frontend/src/services/doraApi.ts`（新增 `askDora` SSE 客户端）；`frontend/src/features/insight/InsightPage.tsx`（AI 判断接入 + 两栏卡片 + 判断列行归类 + 历史先例行 + 抽屉折叠）；`frontend/src/features/pulse/PulsePage.tsx`（专家团 chips + 信号板/卡片收口）；`frontend/src/components/charts/InsightChart.tsx`（等比 + 刻度精度）；`frontend/src/styles.css`（`.insight-drawer*`、`.judge-grid/.judge-col/.verdict-*`、`.signal-*`、`.ev-none`、`.verdict-conf` 等）。
- **后端 / DB**：无改动（`/api/dora/chat`、`/api/insights`、`/api/pulse` 契约不变；消费的是迭代 42 已有的 chat SSE）。
- **依赖**：无新增（不引图表库，SVG 手绘延续）。
- **验证方式**：
  - `cd frontend && npm run build`（tsc -b + vite）
  - 后端回归：`cd backend && python3 -m tests.engine_check`（及归档前 `tests.run_all` 全绿，golden 9 不变）
  - **展示断言（CDP 实测）**：三 tab（problem/opportunity/change）判断列 DOM 文本均不含「下一步建议 / 可参考历史先例 / 历史知识库暂无 / 进一步定位」；下方「下一步建议」面板仍完整；左栏出现「历史先例 · 暂无同指标先例」
  - 人工：1680×2x 截图核对两栏等高、置信度贴底、图表不变形、抽屉收起态、脉搏页 chips 切换
