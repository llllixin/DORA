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
python3 -m tests.engine_check   # 引擎自检（需要数据库已 seed）
```

规则阈值存于 `rule_config` 表（种子默认值见 `app/seed.py`），修改后触发重算即生效。

