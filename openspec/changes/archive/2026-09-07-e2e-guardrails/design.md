## Context

见 proposal.md。现状：c1（华东订单偏弱）在跌破阈值时只改 trigger 文案并标注"等待 V4 升级"，无自动 problem。测试门禁目前为散装命令（engine_check / ingest_check / 冒烟）。

## Goals / Non-Goals

**Goals:** 让"跌破阈值→自动升级 problem"真实发生；把 4 个核心用例固化为 API E2E；提供一键 run_all 门禁。

**Non-Goals:** 定时调度/真实执行器（V4）；浏览器级 UI 测试；把门禁脚本包装进 pytest（保持零新依赖，延续 `python3 -m tests.*` 风格）。

## Decisions

- **升级建模**：在 `evaluate_signals` 中拆分 east 分支——跌破阈值走 `sig-east-breach`（type=problem，insight=`e2`），未跌破走原 c1 change。复用同一 `east_orders` 数据与证据 kind。
- **e2 契约复用现有 Insight 形态**：加 INSIGHT_TEMPLATES/`_semantics`/证据 meta 覆盖 `e2`；`route` 自然为 action（problem 语义）。
- **E2E 靶向运行中 API**（默认 `http://localhost:8000/api`，可用 `DORA_API_BASE` 覆盖），用 urllib 绕过代理直连本地；脚本内自reset（先 sample 重置再按用例注入/还原），可重复执行。
- **run_all 用子进程串联** engine_check / ingest_check / e2e_api_check；任一失败退出非零——与既有门禁风格一致（不加 pytest/httpx 依赖）。

## Risks / Trade-offs

- E2E 依赖后端+DB 在线：文档明示"本地先 docker compose + seed + uvicorn"；属既有运行前提，不新增环境要求。
- 升级为最小行为补齐（Watch 委托/调度仍属 V4）；避免把 V4 全套搬入 C5。
