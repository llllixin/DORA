## 1. 本地 PostgreSQL 环境（Docker）

- [ ] 1.1 新增 `docker-compose.yml`（postgres:16，库/用户/密码 dora，端口 5432），验证：`docker compose up -d` 成功且容器健康
- [ ] 1.2 提供 `DATABASE_URL` 配置入口：`.env.example` 增加 `DATABASE_URL=postgresql+psycopg://dora:dora@localhost:5432/dora`，app 端从环境读取，验证：无 .env 时用默认值可 import

## 2. 数据层（SQLAlchemy）

- [ ] 2.1 新增 `backend/app/models.py`：`metric_series` / `store_cluster_store` / `data_update_log` / `rule_config`（含唯一约束），验证：`python3 -c "from app.models import Base; print(sorted(Base.metadata.tables))"`
- [ ] 2.2 新增 `backend/app/db.py`：engine + session（读取 `DATABASE_URL`）+ `init_db()`（create_all），验证：连上 PG 后 `init_db()` 无异常
- [ ] 2.3 新增 `backend/app/repository.py`：时间序列按 key 读取、集群行/更新事件读取、`rule_config` 的 get/upsert、种子批量 upsert，验证：`python3 -c` 对 seed 后数据读取行数>0
- [ ] 2.4 新增 `DataSourceUnavailableError` 与 FastAPI 503 handler：DB 离线时 `/api/pulse`、`/api/insights` 返回 503 且不含 Mock 数据，验证：`docker compose stop` 后 curl 返回 503，`start` 后恢复 200

## 3. 幂等种子加载

- [ ] 3.1 新增 `backend/app/seed.py`：从 `engine/dataset.py` 把系列/集群/更新事件/规则默认值写入 PG（upsert），验证：`python -m app.seed` 成功
- [ ] 3.2 幂等性：连续执行两次 `python -m app.seed` 后各类行数与首次一致（不翻倍），验证：seed 前后行数相等

## 4. 引擎切换 Repository + 规则配置

- [ ] 4.1 `compute_snapshot(repo, rules)`：从 Repository 读系列/集群/事件；新增 `RULE_DEFAULTS` 与 `rules.get(key)`（DB 有值优先、缺省回退），验证：用 Repository 计算结果与常量版基线一致（pulse 3/2/4/4）
- [ ] 4.2 `evaluate_signals()` 阈值改为从 `rules` 读取（利润率目标/退货基线/华东阈值/集群占比），验证：修改 `rule_config` 中华东阈值后 c1 触发文案随之变化（对照 spec 场景）
- [ ] 4.3 `run_engine()` 接默认 Repository 与规则读取；`backend/tests/engine_check.py` 改为基于 Repository 运行且断言全部通过，验证：`cd backend && python3 -m tests.engine_check`

## 5. 端点与回归

- [ ] 5.1 全链路冒烟（绕过代理环境变量）：5173 代理下 pulse 3/2/4/4、9 条洞察带 semantics、evidence 各 id 非空，验证：`python3 /tmp/dora_smoke.py`
- [ ] 5.2 前端零改动确认：`cd frontend && npm run build` 通过

## 6. 文档与方向看板

- [ ] 6.1 `docs/开发过程记录.md` 追加迭代条目；`docs/版本路线图.md` 勾选 C2；`backend/README.md` 更新运行步骤（docker compose + seed + uvicorn）
- [ ] 6.2 `docs/开发问题与经验.md` 新增决策 D016（SQLAlchemy Repository + 本地 Docker PG + 幂等种子），并记录"urllib 需绕过本地代理"经验已入速查
