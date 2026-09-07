## Why

V2 引擎（迭代 6–9）把"原始经营数据"写成 Python 内存常量（`engine/dataset.py`），规则阈值散落在 `engine.py` 的 if 里。数据随进程重启丢失、规则不可调，无法接真实业务数据；这正是路线图 C2 要解决的"持久化 + 配置化"，也是进入 V3/V4 的前提。

## What Changes

- 新增 **SQLAlchemy 数据层**，本地用 Docker 运行 PostgreSQL 端到端（`DATABASE_URL` 可切环境）。
- 数据模型（4 张表）：
  - `metric_series`：时间序列原始数据（指标 key / 标签 / 维度 / 数值 / 单位），承载利润率、退货、订单、销售额、客单价、新品、高客单、华东订单。
  - `store_cluster_store`：Top 高客单门店行（门店 / 区域 / 客单价）。
  - `data_update_log`：最近一次数据更新事件（时间 / 新增行 / 受影响指标）。
  - `rule_config`：规则参数（key / value / 类型），例如利润率目标 18.5、退货基线 3.2、华东阈值 -3.0、集群机会占比阈值 60。
- **幂等种子加载**：`python -m app.seed`（或启动时自动）把当前演示数据集写入 PG；重复执行不产生重复行（upsert）。
- **引擎数据源切换**：`compute_snapshot()` 从 Repository 读系列/事件/门店行；阈值从 `rule_config` 读取（缺省回退原默认值）。
- 行为契约不变：相同输入数据 → 相同 Pulse/Insight 结果（引擎自检在 PG 数据源上继续通过）。
- 新增 docker 编排：`docker-compose.yml`（postgres 服务）或等价本地 PG 启动脚本；`DATABASE_URL` 进 `.env.example`。

## Capabilities

### New Capabilities
- `business-data-store`: 持久化存储原始经营数据（时间序列、门店集群、更新事件）与规则配置，支持幂等种子加载与按 key 读取，供引擎计算消费。

### Modified Capabilities
- `business-engine`: 引擎的数据来源从"进程内常量"改为"Repository（默认 PostgreSQL）"；规则参数从常量改为可配置（修改 `rule_config` 后，重新计算应反映新阈值）。

## Impact

- 后端：新增 `backend/app/db.py`（engine/session）、`backend/app/models.py`、`backend/app/repository.py`、`backend/app/seed.py`；改 `backend/app/engine/engine.py`（读取层+配置层）、`backend/tests/engine_check.py`（接 Repository 运行）、`requirements.txt`（已含 sqlalchemy/psycopg，无需新增）、新增 `docker-compose.yml`。
- 运行方式变化：引擎端点仍需数据库在线；数据库不可用时返回明确的 503/错误信息（不做静默降级）。
- 前端：**无改动**。
- 非目标（明确不做）：真实上传 `POST /api/datasets`（C3）；Agent/调度（V4）；规则引擎"全声明式 DSL"（保留代码规则形态，仅参数配置化）。
