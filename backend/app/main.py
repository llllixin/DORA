from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers import router
from app.repository import DataSourceUnavailableError

app = FastAPI(title="Dora API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(DataSourceUnavailableError)
async def data_source_unavailable(_request, _exc):
    # spec：数据库不可用不得回退 Mock，返回明确 503
    return JSONResponse(status_code=503, content={"detail": "data source unavailable"})

