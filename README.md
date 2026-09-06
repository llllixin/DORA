# Dora · AI 主动经营驾驶舱 · Full Stack

本仓库把最新 v9 HTML Demo 迁移为 React + TypeScript 前端，同时保留后续 FastAPI / PostgreSQL / Redis / Agent 的工程边界。

## 前端

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://localhost:5173`

## 后端起步

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 当前已实现

- 业务脉搏：摘要、P1 主线、问题栈、其他经营信号、Dora Ask
- 洞察：问题 / 机会 / 变化三类洞察，不同洞察使用不同图表与分析语义
- 行动回路：问题 / 机会 case 对象、步骤、证据链、执行入口、自动编排
- 持续关注：业务目标委托、检查频率、升级路径、关注对象表
- 证据链：统一侧抽屉，支持来源、更新时间、范围、指标、命中证据、原始数据与分析路径
- 状态持久化：行动回路使用 localStorage；URL hash 恢复洞察上下文
- API 层：`src/services/doraApi.ts` 已隔离 Mock 服务与真实 HTTP API 替换点

## 工程下一阶段

1. 把 `doraApi.ts` 的 mock 实现替换为 FastAPI。
2. 建 PostgreSQL：metric / signal / insight / evidence / action_case / action_step / watch_target / execution。
3. Redis + Celery/定时任务负责数据更新后的重算与持续关注。
4. Agent 负责 Intent → Context → Tool → Evidence → Reasoning → Action。
5. Dora 对话改 SSE 流式返回，并回传结构化 evidence refs。
