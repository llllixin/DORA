## Context

见 proposal.md - Why。现状：`engine/dataset.py` 以 Python 常量承载原始数据；`engine.py` 的 `compute_snapshot/evaluate_signals` 直接引用这些常量与内嵌阈值。requirements.txt 已含 sqlalchemy/psycopg。本机 Docker 可用、无本地 PG——本地用 Docker 跑 PostgreSQL 作为开发/测试库。

## Goals / Non-Goals

**Goals:**
- SQLAlchemy 2.0 数据层（models + repository），默认连 PostgreSQL（`DATABASE_URL`）。
- 数据模型承载引擎所需全部原始数据（时间序列/门店集群/更新事件）与规则配置。
- 幂等种子加载：`python -m app.seed`；演示数据集仍以 `dataset.py` 为"种子源"。
- 引擎读取切换为 Repository + 规则配置 Provider，输出与现有自检基线一致。

**Non-Goals:**
- 不做真实上传导入（C3）。
- 不做规则全声明式 DSL / 规则热更新运行时调度（保留代码规则形态，仅参数可配置）。
- 不接 Agent/调度（V4）。

## Decisions

- **Repository 持有"读取"，dataset.py 只当"种子定义"**。`dataset.py` 不再被引擎直接 import 计算；`seed.py` 从它生成行写入 PG，`repository.py` 供引擎读取。备选：引擎直接 SQL → 把判定逻辑和方言耦合，否决。
- **表设计**：
  - `metric_series(metric_key, label, dimension, value, unit)` —— 保留"标签+值"即可还原数组与顺序。
  - `store_cluster_store(store, region, aov)` —— 区域占比/共性在引擎里按快照聚合（沿用现有集群检测规则）。
  - `data_update_log(updated_at, rows_added, total_rows, metrics JSON)` —— 最近一次事件。
  - `rule_config(key PK, value, value_type)` —— 阈值配置，JSON 数字/字符串通用存取。
  - 幂等：用 `(metric_key, label, dimension)` 唯一约束 upsert；`rule_config` 用 PK upsert。
- **配置默认值回退**：`RULE_DEFAULTS` 作为代码内默认值；DB 有值用 DB，缺失回退默认。启动不强制要求 `rule_config` 已种子。
- **依赖注入**：`compute_snapshot(repo, rules)` 接收 Repository 与规则读取函数；`run_engine()` 用应用默认 Repository（读 `DATABASE_URL`）。测试与 API 共用同一路径。
- **错误语义**：Repository 连接失败抛 `DataSourceUnavailableError` → 端点返回 503（FastAPI exception handler），与 spec 一致，绝不静默回退 Mock。
- **本地 PG**：新增 `docker-compose.yml` 提供 postgres（db dora / user dora / pass dora / port 5432）；`.env.example` 加 `DATABASE_URL`；开发脚本先 `docker compose up -d`。

## Risks / Trade-offs

- 每次引擎端点请求都会触 DB 查询（当前是常量读）→ 增加查询次数与延迟；缓解：指标级读取一次性拉取 + 会话级小查询集，属可接受范围；性能优化（缓存/物化）留后续。
- PostgreSQL 方言（JSONB、upsert）依赖真实 PG → 本地必须能跑 Docker PG，apply 验收在容器内验证；若 Docker 环境失败需暂停询问。
- 并发写种子与读：种子 upsert 幂等，重复执行安全。
- 引擎结果与"前端 Watch 等静态域"解耦现状不变，避免意外耦合。

## Migration Plan

- 无既有数据库迁移需求（本仓库尚无 schema）；用 `Base.metadata.create_all` + seed 完成初始化（后续引入 Alembic 前够用）。
- 部署/回滚：单次提交；回滚即 revert，前端不受影响。
- 本地运行顺序：`docker compose up -d` → `python -m app.seed` → `uvicorn`。
