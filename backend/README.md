# Dora Backend Starter

这是与 React 前端对应的 FastAPI 起步层。当前只提供 health / pulse 两个最小接口；业务服务、Agent、数据库、Redis 依照《完整详细的搭建说明流程.md》逐步实现。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
