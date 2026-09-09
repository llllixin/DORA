## 1. 前置：委托链路核对 + 字段盘点基线

- [x] 1.1 后端在线 curl 实测委托解析与建档链路：parse「关注利润率，连续 3 天下跌提醒我」→ `ok=true` + `metric_key=margin` + `condition:{type:streak_below,days:3}` + `condition_defaulted=false`；POST /api/watch 建档 `w-114962088237` → GET /api/watch 列表可见 → DELETE 成功（输出已留档）
- [x] 1.2 字段盘点表固化（propose 补强 2）：`pulseView.ts` 头注释维护「Pulse 面板 → 字段 → 来源 → 降级文案」映射；PulsePage 不消费 `/api/pulse` → 验证 `grep -nE '/api/pulse' PulsePage.tsx` 无命中（exit=1）+ `npm run build` 绿
- [x] 1.3 记录清理基线（已记录）：改动前 `grep -nE 'const view|p[0-9]|PRF-0831' PulsePage.tsx` 命中 const view 字典 / p1 分支 / PRF-0831 假卡（输出留档）；模式已修正为无转义、可判定的写法

## 2. Pulse 主区 / 信号板 / 监控卡真实化

- [x] 2.1 新增 `pulseView.ts`：`heroFor`/`signalsFrom`/`monitorsFrom` 纯函数 + 字段盘点头注释 → `cd frontend && npm run build` 绿（48 modules）
- [x] 2.2 主区改用 `heroFor`，删除 `view[p.id]` 字典与 `p.id==='p1'` 分支；展示字段来自引擎 → build 绿；在线 curl `/api/insights?type=problem` 与页面同源（desc/semantics 拼接）
- [x] 2.3 信号板/监控卡改读派生数据（opportunity+change / watchItems）→ build 绿；离线镜像自检 monitors=watchItems 数量一致
- [x] 2.4 删除伪造「PRF-0831 每日检查供应商 B」演示卡 → `grep -c 'PRF-0831' PulsePage.tsx` = 0
- [x] 2.5 默认焦点与空态（review P1-2）：默认取 `insights.problem[0]?.id` + clamp effect + 无 problem 空态 → 代码实现 + build 绿（浏览器换数据集场景并入 5.3 人工项）

## 3. 离线镜像迁移（补强 1：删字典 ≠ 离线空壳）

- [x] 3.1 `data.ts`：demo 洞察 p1–p3 补结构化 semantics/evidence（镜像原归因文案）→ build 绿；esbuild 自检：`heroFor(p1)` facts=2（非空壳）
- [x] 3.2 `data.ts`：`watchItems` 类型升级为 `WatchTargetCard[]`（可承载 status），`monitorsFrom` 正常消费 → build 绿；离线自检 monitors=6/6
- [x] 3.3 验收断言：停后端（auto）Pulse 整体观感与改动前 demo 一致 + 「离线演示」标识 → ✅ 人工浏览器冒烟通过（截图留档见会话记录）

## 4. 「让 Dora 帮我跟进」接真实 Watch

- [x] 4.1 `followTargetFor`：margin →「关注利润率，连续 3 天下跌提醒我」（显式 streak_below days=3、defaulted=false）；returns/orders 返回 null → esbuild 自检断言通过
- [x] 4.2 跟进按钮真实化：handler 已实现（detectApi 前置 / createWatch 真实 target / 失败显式提示 / syncRemoteData 同源刷新）→ ✅ 人工浏览器双态点击验证通过（在线建档真实落库、停后端显式提示且不假建档）
- [x] 4.3 已关注态与取消：handler 已实现（初始态由 watchItems 推导 / 取消先 detectApi 防 deleteWatch 假 ok / 同源刷新）→ ✅ 人工浏览器双态点击验证通过（在线取消生效并回未关注态、停后端提示且无假成功）

## 5. 回归与冒烟

- [x] 5.1 静态断言清理完成：`grep -nE 'const view|p[0-9]|PRF-0831' frontend/src/features/pulse/PulsePage.tsx` **无命中**（exit=1，1.3 基线反转）
- [x] 5.2 一键门禁：`cd backend && PATH=/Users/tomara/miniforge3/bin:$PATH python3 -m tests.run_all` → **run_all: ALL GREEN**（含 reasoning/golden 9/e2e 4/watch 4 节/action 6 节；注：本机 python3 为 homebrew 需 PATH 指到 miniforge，B1 backlog）
- [x] 5.3 `cd frontend && npm run build` 绿；浏览器冒烟双态（在线=各面板与洞察/Watch 一致+跟进真实落库；停后端=与改动前 demo 观感一致+「离线演示」提示+跟进/取消不假成功）→ ✅ 人工确认通过
- [x] 5.4 AskBar 保留回归（review P1-5）：PulsePage 仍渲染 `<AskBar>`（1 处）且提交仍为占位提示 → build 绿
- [x] 5.5 backlog 同步（review P3-8）：`docs/持续优化路线.md` §3D.1 接口已标注「/api/pulse 仅纯计数、面板走 /api/insights+/api/watch」；本 change 全程未消费 `/api/pulse`（grep exit=1）→ 归档时确认勾选
