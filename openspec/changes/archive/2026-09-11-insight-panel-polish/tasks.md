## 1. 前置：现状证据 + 基线

- [x] 1.1 留档问题证据：`curl -s --noproxy '*' -X POST http://localhost:8000/api/dora/chat -H 'Content-Type: application/json' -d '{"question":"为什么「利润率低于目标」值得处理？","insight_id":"p1","page":"insight"}' | grep -A2 'event: answer'` → answer.text 含 4 段（`主要影响因素` / `进一步定位` / `下一步建议：…` / `历史知识库暂无同指标先例。`），据此定位判断列复述成因（后端 `_compose_answer` 无条件追加 next/refs）
- [x] 1.2 记录改动前基线：CDP 读 `.judge-col.verdict` innerText 含「下一步建议」→ 作为 7.3 断言的**反转基线**（改后同读取必须不含）
- [x] 1.3 确认后端零改动：`git diff --stat backend/` 为空；`git status --short` 只含本轮 5 个前端文件 + 本次 docs/openspec 变更

## 2. 洞察页 AI 判断接入（doraApi.ts + InsightPage.tsx）

- [x] 2.1 `doraApi.ts` 新增 `askDora(question, {insightId, page})`：`POST /dora/chat` + SSE 逐事件解析（空行分帧；取 `answer.text/references`、`thought_step.intent`、`done.run_id`），20s 超时 + `AbortController`，`MODE==='mock'` 直接抛错 → 验证：`grep -n 'export async function askDora' frontend/src/services/doraApi.ts` 命中；`npm run build` 绿
- [x] 2.2 `InsightPage.tsx` 判断三态：loading「正在结合证据判断…」/ 成功用 `answer.text` / 失败或离线 → `semantics` 兜底句 + `verdict-note`「AI 暂不可用，以上为引擎语义兜底」；换洞察时 `setRestOpen(false)` 重置展开态 → 验证：停后端（或 `VITE_API_MODE=mock`）时判断列不空白且出现兜底 note；在线时 `.verdict-lead` 文案 = chat answer 首句

## 3. 判断列去复述 + 历史先例行（本轮主修复）

- [x] 3.1 新增 `belongsElsewhere` 行归类（归因行 → 左栏归因卡 / `下一步建议：` → 下方面板 / `可参考历史先例|历史知识库暂无同指标先例` → 左栏先例行），派生 `ownRest`；`shownRest = restOpen ? ownRest : ownRest.slice(0,2)`、`moreRest = ownRest.length - shownRest.length`（**展开也不带出**归类行）→ 验证：`grep -n 'belongsElsewhere\|ownRest' frontend/src/features/insight/InsightPage.tsx` 命中
- [x] 3.2 结论句仍**逐字**来自引擎/chat 原文（`splitVerdict` 不改写）→ 验证：CDP 读 `.verdict-lead` = chat answer 首句
- [x] 3.3 头部「字段盘点表」补「判断列」来源行 + 去重规则注释（含示例原文）→ 验证：`sed -n '1,20p' frontend/src/features/insight/InsightPage.tsx` 可见两行注释
- [x] 3.4 左栏「历史先例」行三态（命中 → `先例标题（code）`／chat 成功且无引用 → `暂无同指标先例`（`.ev-none`）／`judge.loading || judge.err` → 不渲染）；置信度贴卡片底 `.verdict-conf{margin-top:auto;padding-top:14px}` → 验证：CDP 断言 `.judge-col.judge-facts` 含「历史先例 暂无同指标先例」；`grep -n 'verdict-conf\|ev-none' frontend/src/styles.css` 两条命中；`.judge-grid` 仍为 `align-items:stretch`（无 `start`）

## 4. 洞察列表抽屉 + 两栏卡片布局（InsightPage.tsx / styles.css）

- [x] 4.1 洞察列表改可折叠抽屉（`.insight-shell` grid→flex；`.insight-drawer` 展开 300px / 收起 46px；`listOpen` 默认展开 + `.drawer-toggle`）→ 验证：CDP 点击 `.drawer-toggle` 断言 drawer 宽 300→46、`.detail` 卡宽增大，再点复原；截图 `drawer_closed.png`
- [x] 4.2 归因卡两列并排（`.cause-grid` 两列）+ 事实/判断两栏等宽等高（`align-items:stretch`）→ 验证：CDP 读两 `.judge-col` 的 `getBoundingClientRect()` 宽高相等（±1px）；截图 `judge.png`

## 5. 图表等比 + 纵轴刻度精度（InsightChart.tsx）

- [x] 5.1 5 处 `preserveAspectRatio="none"` → `"xMidYMid meet"`（`.chart-area svg` 是 `width:100%;height:100%` 的固定 300px 高容器，`none` 会把 760×300 坐标系非等比拉伸）→ 验证：`git --no-pager diff -U0 frontend/src/components/charts/InsightChart.tsx | grep 'preserveAspectRatio' | grep -c '^+'` 的新增行全部为 `"xMidYMid meet"`（`grep -c '^+.*"none"'` = 0）；CDP 在 1400/1680/1920 三视口下读 `.chart-area svg circle:first-of-type` 的 `getBoundingClientRect()`，`width/height ≈ 1`（±0.05，圆不再被拉成椭圆）
- [x] 5.2 纵轴刻度按 `tickStep=(mx-mn)/5` 决定小数位（`≥1→0 / ≥.1→1 / 否则 2`）+ `-0` 归一 → 验证：CDP 读 p1 图纵轴 6 个刻度文本互不相同（无 `20% / 20%` 重复）；`grep -n 'tickStep' frontend/src/components/charts/InsightChart.tsx` 命中

## 6. 脉搏页展示收口（PulsePage.tsx）

- [x] 6.1 「自动编排 · 专家团能力说明」改可点 chips（数据：`data.ts` 的 `capabilities.专家团` + `autoExpertNotes`；默认选第一位，点击切换「名称：说明 + 备注」）→ 验证：CDP 点击第二个 chip 后 `.auto-note` 文本随之变化；截图 `pulse_chips.png`
- [x] 6.2 信号板卡片布局（`.signal-board / .signal-board-head / .signal-row / .signal-main / .signal-value(.base,.delta) / .signal-action`：数值与变化不换行、按钮右对齐）+ 移除「持续关注」卡片「?」note（`Summary` 去掉 `note` prop、`.summary-card .q` 规则删除并在 styles.css 留注释）→ 验证：CDP 断言 `document.querySelector('.summary-card.watch .q')` 为 null；每条 `.signal-row` 内存在 `.signal-action`；`page=pulse` 无横向溢出（`scrollWidth <= clientWidth + 1`）

## 7. 回归与门禁（归档前必跑）

- [x] 7.1 `cd frontend && npm run build` → tsc -b + vite 全绿（以实际输出为准）
- [x] 7.2 后端回归（本机 PATH 首位 homebrew 无 sqlalchemy，须前置解析器，见 P012）：`cd backend && PATH=/Users/tomara/miniforge3/bin:$PATH python3 -m tests.engine_check` → `engine self-check OK` + `pulse = {'problems': 3, 'opportunities': 2, 'changes': 4, 'watching': 4}`；归档前再跑 `PATH=/Users/tomara/miniforge3/bin:$PATH python3 -m tests.run_all`（ALL GREEN、golden 9 不变，守门「后端零改动」）
- [x] 7.3 CDP 展示断言（三 tab）：`node /tmp/dora_judge_verify.mjs` → 期望 `[PASS] 三 tab 判断列均与其它区块无重复；下一步建议/先例各归其位`（断言判断列不含「下一步建议 / 可参考历史先例 / 历史知识库暂无 / 进一步定位」，下方面板与左栏先例行完整）
- [x] 7.4 人工截图核对（1680×2x）：`/tmp/dora_shots/panel.png`、`judge.png`、`drawer_closed.png`、`pulse_chips.png` → 两栏等高、置信度贴底、图表不变形、抽屉收起态、chips 切换正常
- [x] 7.5 文档与 OpenSpec 同步：`docs/持续优化路线.md` 勾选本项（附验证摘要）+ `docs/开发过程记录.md` 追加「迭代 43」（含【测试证据】+【反思】）+ `docs/开发问题与经验.md` D039 状态更新为已生效 → 验证：`cd backend && python3 -m tests.check_docs` ALL GREEN；`openspec validate insight-panel-polish --strict` 通过

## 验证记录（apply 实测，2026-09-11；完整流水见 `docs/开发过程记录.md` 迭代 43）

- 1.1 chat why 原文 4 段复现（curl）：`...「利润率低于目标」的判断来自引擎：连续 4 天低于目标，成本端出现可干预因素。\n主要影响因素：A 产品线采购成本 较期初 2.2%\n进一步定位：供应商 B 较同行高 10.9%\n下一步建议：核对…\n历史知识库暂无同指标先例。`
- 1.2 基线证据（**流程偏差，已承认**）：HEAD 版本尚无判断列（`git show HEAD:…InsightPage.tsx | grep -c 'judge'` = 0），修复前 DOM 无快照可回放 → 以「chat 原文确含 4 段（1.1）」+「反转断言实测（7.3 / 2.2：判断列不含 4 类文本）」双向证据替代，未伪造 baseline 数值
- 1.3 `git diff --stat backend/` 空（0 行）；`git status --short` 仅 5 前端文件 + 3 docs + 本 change
- 2.1 `grep -c 'export async function askDora' doraApi.ts` = 1；`npm run build` 通过
- 2.2 在线：`.verdict-lead` 与 chat 首句逐字相同（CDP）；降级（CDP `Fetch.failRequest` 拦截 `/api/dora/chat`）→ **6/6 PASS**：`主要因素：A 产品线采购成本…` 兜底 + `AI 暂不可用，以上为引擎语义兜底` + 不复述 + 不伪造先例 + 下方面板不丢 + 置信度仍在；截图 `offline_fallback.png`
- 3.1 `grep -c 'belongsElsewhere\|ownRest'` = 6；CDP `dup={"next":false,"prev":false,"ref":false,"fact":false}`（含展开态）
- 3.2 CDP：`lead == chat answer 首句`（逐字，见 2.2）
- 3.3 头部注释可读：`sed -n '18,19p'` 命中「规则：判断列不重复其它区块已有的行…」
- 3.4 CDP：`.judge-col.judge-facts` 含「历史先例 暂无同指标先例」；`grep -c 'verdict-conf\|ev-none' styles.css` = 2；`.judge-grid{…align-items:stretch}`
- 4.1 CDP：drawer 300 → 46（`.card.detail` 1072 → 1326），再点复原 300；截图 `drawer_closed.png`
- 4.2 CDP：两栏 `[{w:496,h:239},{w:496,h:239}]` 等宽等高；`.cause-grid` = `repeat(2,minmax(0,1fr))` 实测 `229px 229px`；截图 `judge.png`
- 5.1 `git diff -U0` 统计：旧 `preserveAspectRatio="none"` 删除 5 行、新增 `"xMidYMid meet"` 5 行、新增含 `none` 0 行；CDP 三视口圆点宽高比 `{"1400":1,"1680":1,"1920":1}`
- 5.2 `grep -c tickStep` = 1；CDP 纵轴刻度 `["18.2%","18.7%","19.3%","19.9%","20.5%","21.0%"]`（6 个、互不重复；旧 `fmt()` 会给出 `18%/19%/19%/20%/20%/21%`）
- 6.1 CDP：chips = 4，点击第二个 `auto-note` 由「经营分析专家：问题拆解 / 经营判断」→「财务专家：利润与指标口径」；截图 `pulse_chips.png`
- 6.2 CDP：`.summary-card.watch .q` = false；`signal-row=6` 且 6/6 含 `.signal-action`；`scrollWidth-clientWidth=0`；截图 `pulse_signals.png`
- 7.1 `cd frontend && npm run build` → `✓ 47 modules transformed / ✓ built`（tsc -b + vite）
- 7.2 `PATH=/Users/tomara/miniforge3/bin:$PATH python3 -m tests.engine_check` → `engine self-check OK` + pulse `{'problems': 3, 'opportunities': 2, 'changes': 4, 'watching': 4}`（9 insights 值不变）；`… python3 -m tests.run_all` → **ALL GREEN**（golden 9 不变，e2e 4 用例）
- 7.3 `node /tmp/dora_judge_verify.mjs`（三 tab + 展开态）→ `[PASS] 三 tab 判断列均与其它区块无重复；下一步建议/先例各归其位`
- 7.4 截图核对：`panel.png / judge.png / drawer_closed.png / pulse_chips.png / pulse_signals.png / offline_fallback.png`（1680 宽 2x）
- 7.5 `docs/持续优化路线.md` 勾选 + 追加两项候选（死 CSS / `insight-judgment-structure`）；`docs/开发过程记录.md` 迭代 43；`docs/开发问题与经验.md` D039 状态 + 新增 P013 → `python3 -m tests.check_docs` ALL GREEN；`openspec validate insight-panel-polish --strict` 通过
- **apply 期间发现并修复**（记入 P013）：`className="judge-col facts"` 撞上遗留全局 `.facts{margin-top:9px}` → 两栏高度 255/264 不等；重命名 `judge-facts` 后 239/239 等高

