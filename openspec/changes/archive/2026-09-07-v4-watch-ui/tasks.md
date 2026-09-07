## 1. 后端 watch REST

- [x] 1.1 `schemas.py` 增 `WatchCreateRequest{text,frequency?}` / `WatchStatusRequest{status}`；`evaluator.evaluate_one` 单目标（engine_insights=None）惰性 `run_engine`；验证：见 1.2 冒烟与 run_all
- [x] 1.2 `routers.py`：替换静态 GET /watch 为 DB 卡片列表；新增 POST /watch（parse→400 detail / create→即时评估）、GET /watch/{id}（含事件）、PATCH status、DELETE、POST /watch/{id}/check；验证：冒烟脚本 create→list→pause→check→delete 全链路 JSON

## 2. 前端真实化

- [x] 2.1 `types.ts` WatchItem 增可选 status/frequency/lastEventAt；`doraApi.ts` 增 parseWatch/createWatch/setWatchStatus/deleteWatch/checkWatch 并补 PATCH/DELETE 请求助手；验证：`npm run build` 通过
- [x] 2.2 WatchPage：输入→parse 回显（或 unsupported toast）→确认创建；列表操作（暂停/恢复/删除/检查）刷新；chips 保持 6 个；Pulse 侧：Summary 计数实时、监控文案去静态声明；验证：build + 页面冒烟（后端在线时 Watch 列表=DB 委托）

## 3. 收尾

- [x] 3.1 回归：`python3 -m tests.run_all` 6 段 ALL GREEN；watch_check 不回归
- [x] 3.2 dev-log「迭代 25」+ 路线图 §3B V4-T4 标记 + archive（【测试证据】+【反思】）

【测试证据】npm run build ✅（tsc + vite 46 modules）；run_all → ALL GREEN（6 段，golden 9 不变）；watch REST 冒烟（绕代理）：POST /watch 200（华东销售额/watching/有变化→即时评估命中）、GET /watch 1 条、PATCH paused（已暂停）、POST check（change）、未知指标 400 detail、DELETE ok ✅。
【反思】路径同名注意：/watch 与 /watch/{watch_id} 共存时 FastAPI 按注册顺序匹配、方法允许矩阵需整体可用（本次踩 405 实为进程未重载旧代码而非路由问题——先确认进程加载新代码再排查路由）；卡片保持 WatchItem 超集让 Pulse/Topbar 零改动消费真实委托；创建=parse+落库+即时评估使"创建即有初判"；4xx 业务拒绝必须显式上抛而 5xx/断网才走 mock，避免不支持指标被静默创建。
