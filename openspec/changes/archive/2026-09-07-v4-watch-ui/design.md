## Context

见 proposal.md。后端已有 repo CRUD、parser、evaluator/scheduler；前端已有三模式 doraApi 与 data.ts 兜底结构。T4 目标 = 把两者用 REST 接上，旧 Watch 页的静态 setParsed 让位给 parse 回显。

## Goals / Non-Goals

**Goals:** watch REST 五端点 + 前端 Watch/Pulse 消费真实数据（创建/列表/暂停/删除/检查），WatchItem 形状保持兼容（前端离线兜底不变）。

**Non-Goals:** AskBar 追问真实化（仍 mock，另立）；Action 页真实化（V5）；Dora Chat；Watch 分页/筛选 UI；多端实时推送（轮询即可）。

## Decisions

- **卡片形状兼容优先**：GET /api/watch 返回字段仍为 {id,name,value,color,logic,source} + 新增可选 status/frequency/lastEventAt —— Pulse/Topbar 等所有消费 watchItems 的组件零改动升级；离线兜底 data.ts watchItems 结构不变。
- **status 语义落 value/color**：escalate→"已升级"/red；change→"有变化"/blue；watching 无事件→"观察中"/green；paused→"已暂停"/blue。
- **创建 = parse + repo.create + 即时评估一次**（POST /watch）：unsupported 走 400 detail 让前端 toast 显示原因；createFollowup 旧 mock 语义不保留（Insight 详情 follow 按钮行为在 T5 前不承诺）。
- **evaluate_one 惰性 run_engine**：单目标手动 check（无共享 insights）时自行跑一次 run_engine，保证 escalate 判定不缺失（修复 T3 单查路径漏洞）。
- **暂停即免评估**：evaluate_all/_tick 均按 status=watching 过滤（T1 repo 创建/调度已如此，PATCH 只改 status）。
- 前端每次操作后重新 GET /watch 刷新本页与 Pulse（无状态管理引入，沿用现有原位刷新模式）。

## Risks / Trade-offs

- 旧"查看"洞察路由对 w- 委托不适用 → Watch 行主操作改为"检查"（手动评估），洞察跳转留给对应引擎事件。
- GET /api/watch 从静态 WATCH 改为 DB 读取 → 后端离线时前端走 data.ts 兜底，语义降级为静态演示（UI 文案有"离线演示"字样已在 doraApi 兜底路径注明）。
- REST 无鉴权/限流 → 当前单机工具产品阶段可接受（多用户部署前统一加）。
