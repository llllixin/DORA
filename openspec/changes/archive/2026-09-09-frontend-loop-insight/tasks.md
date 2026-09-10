## 1. 前置：基线 + 字段盘点固化

- [x] 1.1 记录清理基线：改写前 `grep -nE 'const (next|cause|n1|n2)|p[0-9]:|o[0-9]:|c[0-9]:' InsightPage.tsx` 命中写死 `next/cause/n` 字典（输出留档）→ 改写后同命令无命中（exit=1，4.1 反转）
- [x] 1.2 字段盘点固化（补强 2）：InsightPage 头部注释维护「归因卡 / 置信来源 / 下一步 / 图表 → 字段 → 来源 → 降级文案」映射表（design D3）→ `npm run build` 绿 + 注释存在

## 2. InsightPage 静态回退下线 + 缺省诚实

- [x] 2.1 删除按 id 写死的 `next`/`cause1/cause2/n1/n2` 与 `x.id==='pN'` 分支；cause/next 只读 `x.semantics`（semFacts 派生）；→ 验证：`grep -c 'const next:Record'` = 0；build 绿；在线冒烟归因=引擎 semantics（并入 4.3 人工）
- [x] 2.2 无 semantics 降级：`semFacts=[]` 时归因区显「模板未覆盖 / 引擎原文」note（metric·delta·question），下一步显示「暂无引擎建议（可重新解释刷新）」空态，无编造值 → 代码路径编译 + grep 无旧假值分支；人工视觉并入 4.3
- [x] 2.3 保留 AskBar / FollowupCard / InsightChart / 「加入行动回路|加入持续关注」/ 重新解释 → 验证 `grep -cE '<AskBar|<FollowupCard|InsightChart'` = 4、build 绿

## 3. 离线镜像迁移（补强 1：删字典 ≠ 离线空壳）

- [x] 3.1 `data.ts`：o1/o2/c1–c4 补结构化 semantics（causeA/causeB/next 等价被删写死文案），p1–p3 已有 → 验证 `grep -c "semantics: { causeA" src/data.ts` = **9**（9/9 全覆盖）、build 绿
- [x] 3.2 停后端（auto）Insight 页观感与改动前 demo 一致（归因 chips / 下一步仍在）→ ✅ 人工浏览器冒烟通过（截图留档见会话记录）

## 4. 回归与冒烟

- [x] 4.1 静态断言反转：`grep -nE 'const (next|cause1|cause2|n1|n2)|causeA=sem|next\[x\.id\]' InsightPage.tsx` 无命中（exit=1）
- [x] 4.2 `cd frontend && npm run build` 绿（dist 286 KB）；`/Users/tomara/miniforge3/bin/python3 -m tests.run_all` → **ALL GREEN**（后端零改动回归确认）
- [x] 4.3 浏览器双态冒烟：在线=归因/下一步与引擎 semantics 一致；停后端=与改动前 demo 观感一致 + 无假值 → ✅ 人工浏览器确认通过（含无 semantics 降级抽查）
