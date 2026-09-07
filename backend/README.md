# Dora Backend Starter

FastAPI 后端：提供 REST API，业务数据存 PostgreSQL（本地开发用 Docker 运行），引擎从 Repository 读取并计算 Pulse / Insight / Evidence。

## 本地运行

```bash
# 0) 起 PostgreSQL（Docker）
cd .. && docker compose up -d

# 1) 初始化表结构 + 灌入演示种子（幂等，可重复执行）
cd backend
python -m app.seed

# 2) 启动 API（默认 :8000，/api 供 frontend 5173 代理）
python3 -m uvicorn app.main:app --reload --port 8000
```

## 配置

- `DATABASE_URL`（默认 `postgresql+psycopg://dora:dora@localhost:5432/dora`），可从 `backend/.env` 覆盖（参考 `.env.example`）。
- 引擎运行要求数据库在线；DB 不可用时引擎端点返回 `503`（不回退 Mock）。

## API（当前）

- `GET /api/health`、`GET /api/pulse`（引擎计算）
- `GET /api/insights?type=problem|opportunity|change`、`GET /api/insights/{id}`
- `GET /api/evidence/{id}`、`GET /api/actions[/{id}]`、`POST /api/actions/{id}/execute`、`GET /api/watch`
- `GET /api/engine/run`（全链路快照诊断）

## 验证

```bash
python3 -m tests.run_all   # 一键门禁：engine_check + ingest_check + e2e_api_check（需 DB + 后端 :8000 在线）
```

- `python3 -m tests.engine_check`：引擎判定回归。
- `python3 -m tests.ingest_check`：上传/映射入库回归。
- `python3 -m tests.e2e_api_check`：文档第 36 章 4 个核心用例（Problem/Opportunity/Change→Watch/Watch→自动升级 Problem）。

规则阈值存于 `rule_config` 表（种子默认值见 `app/seed.py`），修改后触发重算即生效。

## 数据上传（C3）

```bash
# 服务端载入/重置演示样例（出厂状态）
curl -X POST http://localhost:8000/api/datasets/sample

# 上传规范格式文件（csv/xlsx），事务替换其指标 key 并登记更新事件
curl -F 'file=@/path/to/data.csv' http://localhost:8000/api/datasets

# 当前数据源摘要
curl http://localhost:8000/api/datasets/current
```

**引擎输入规范格式**：表头 `metric_key,label,dimension,value,unit`。
支持 metric_key：`margin / returns / orders / revenue / aov / east_orders / new_sku / high_value / supplier_price`。
限制：≤10MB；非法内容返回 400；数据库离线返回 503。任意业务口径的映射向导属后续迭代（C4）。

### 任意列布局 → 映射入库（C4）

```bash
# 1) 预览列结构（不落库）
curl -F 'file=@/path/any.csv' http://localhost:8000/api/datasets/preview

# 2) 声明列映射后入库（file + mapping JSON）
curl -F 'file=@/path/any.csv' \
     -F 'mapping={"metric_key":"margin","label_column":"date","value_column":"margin_value","dimension_column":"region"}' \
     http://localhost:8000/api/datasets/mapped
```

映射字段：`metric_key`（白名单）、`label_column`、`value_column`、可选 `dimension_column`/`unit`。

