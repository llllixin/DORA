"""Additive read-only graph API; building is local CLI only."""
from fastapi import APIRouter,Depends,Query
from fastapi.responses import JSONResponse
from app.graph.contracts import GraphRequest,GraphError
from app.graph.service import GraphService

router=APIRouter(prefix='/api/graph',tags=['graph'])
def get_graph_service():return GraphService()
def call(operation):
    try:return operation()
    except GraphError as exc:return JSONResponse(status_code=exc.status_code,content={'detail':{'reasonCode':exc.code}})


@router.get('/status')
def status(service=Depends(get_graph_service)):
    return call(service.status)


@router.post('/neighborhood')
def neighborhood(request:GraphRequest,service=Depends(get_graph_service)):
    return call(lambda:service.neighborhood(request))


@router.get('/relations/{relation_id}/evidence')
def evidence(relation_id:str,batchId:str=Query(min_length=1,max_length=160),includeSimulated:bool=False,
             service=Depends(get_graph_service)):
    return call(lambda:service.evidence(relation_id,batchId,include_simulated=includeSimulated))
