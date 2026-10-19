from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app import db
from app.routers import router
from app.repository import DataSourceUnavailableError
from app.rag import RagService
from app.rag.contracts import RagIndexConflict, RagIndexUnavailable
from app.runtime.contracts import RuntimeFailure
from app.watch import scheduler as watch_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # watch-escalate-handoff：启动即跑幂等建表/DDL/数据迁移（含 watch 升级终态 backfill）。
    # DB 不可用时不阻断启动（读接口照旧返回 503），行为与既有"启动不依赖 DB"一致。
    try:
        db.init_db()
        # 小型本地知识库启动时幂等同步；默认哈希 embedding 不产生外部调用。
        RagService().rebuild_index()
    except Exception as exc:  # noqa: BLE001 - 数据源不可用不该让服务起不来
        print(f"[startup] init_db skipped: {exc}")
    watch_scheduler.start()  # V4-T3：周期调度（daily/weekly 委托）
    yield
    watch_scheduler.stop()


app = FastAPI(title="Dora API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
from app.evidence.router import router as evidence_router
from app.evidence.contracts import EvidenceError
app.include_router(evidence_router)

from app.ingest import IngestCapacityError

@app.exception_handler(IngestCapacityError)
async def ingest_capacity_error(_request,exc):
    return JSONResponse(status_code=413,content={'detail':str(exc),'reasonCode':'dataset_capacity_exceeded'})


@app.exception_handler(EvidenceError)
async def evidence_error(_request,exc):
    return JSONResponse(status_code=exc.status_code,content={'detail':exc.code,'reasonCode':exc.code})

from app.query.router import router as query_router
app.include_router(query_router)
from app.graph.router import router as graph_router
app.include_router(graph_router)


@app.exception_handler(RagIndexConflict)
async def rag_index_conflict(_request, exc):
    return JSONResponse(status_code=409, content={'detail': {'reasonCode': exc.code, 'runId': getattr(exc, 'run_id', None)}})


@app.exception_handler(RuntimeFailure)
async def runtime_unavailable(_request, exc):
    return JSONResponse(status_code=503, content={'detail': {'reasonCode': exc.category, 'runId': getattr(exc, 'run_id', None)}})


@app.exception_handler(RagIndexUnavailable)
async def rag_index_unavailable(_request, exc):
    return JSONResponse(status_code=503, content={'detail': {'reasonCode': exc.code, 'runId': getattr(exc, 'run_id', None)}})


@app.exception_handler(DataSourceUnavailableError)
async def data_source_unavailable(_request, _exc):
    # spec：数据库不可用不得回退 Mock，返回明确 503
    return JSONResponse(status_code=503, content={"detail": "data source unavailable"})
