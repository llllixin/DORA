"""HTTP adapter for the separately versioned unified read-only query contract."""
from fastapi import APIRouter,Depends
from fastapi.responses import JSONResponse
from app.query.contracts import QuerySearchRequest,QueryAnswerRequest,QueryError
from app.query.service import default_service
from app.query.evidence import read_run_evidence

router=APIRouter(prefix='/api/query',tags=['query'])
def get_query_service():return default_service()
def get_run_repository():
    from app.repository import Repository
    return Repository()
def _call(call):
    try:return call()
    except QueryError as exc:return JSONResponse(status_code=exc.status_code,content={'detail':{'reasonCode':exc.code,'runId':exc.run_id}})

@router.post('/search')
def search(request:QuerySearchRequest,service=Depends(get_query_service)):
    return _call(lambda:service.search(request))
@router.post('/answer')
def answer(request:QueryAnswerRequest,service=Depends(get_query_service)):
    return _call(lambda:service.answer(request))
@router.get('/runs/{run_id}/evidence/{evidence_id}')
def evidence(run_id:str,evidence_id:str,repository=Depends(get_run_repository)):
    return _call(lambda:read_run_evidence(repository,run_id,evidence_id))
