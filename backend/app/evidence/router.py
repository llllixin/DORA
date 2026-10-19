"""Strict historical endpoints; GET does not calculate or persist facts."""
from contextlib import contextmanager
from fastapi import APIRouter
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.evidence.contracts import EvidenceError
from app.evidence.migrations import require_evidence_ready
from app.evidence.repository import EvidenceRepository
from pydantic import BaseModel,Field

router=APIRouter(prefix='/api/history')


class OpenCaseRequest(BaseModel):
    insightTypeId:str=Field(min_length=1,max_length=32)
    expectedRevision:str=Field(min_length=1,max_length=128)
    sourceWatchBindingId:str|None=Field(default=None,max_length=80)


@router.post('/action-cases')
def open_case(request:OpenCaseRequest):
    from app.repository import Repository
    from app.evidence.action import create_case_captured
    from fastapi import HTTPException
    try:
        return {'ok':True,**create_case_captured(Repository(),insight_type_id=request.insightTypeId,
            expected_revision=request.expectedRevision,source_watch_binding_id=request.sourceWatchBindingId)}
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@contextmanager
def history_reader():
    try:
        engine=db.get_engine();require_evidence_ready(engine)
        with Session(engine) as s:yield EvidenceRepository(s)
    except EvidenceError:raise
    except SQLAlchemyError as exc:raise EvidenceError('evidence_unavailable',503) from exc


@router.get('/snapshots/{snapshot_id}')
def snapshot(snapshot_id:str):
    with history_reader() as store:
        value=store.get_snapshot(snapshot_id)
        if value is None:raise EvidenceError('not_found',404)
        return {'ok':True,'snapshot':value}


@router.get('/bindings/{binding_id}')
def binding(binding_id:str):
    with history_reader() as store:
        value=store.get_binding(binding_id)
        if value is None:raise EvidenceError('not_found',404)
        return {'ok':True,'binding':value}


@router.get('/action-cases/{case_id}')
def case_history(case_id:str):
    with history_reader() as store:return {'ok':True,'history':store.case_history(case_id)}


@router.get('/watch-events/{binding_id}')
def watch_history(binding_id:str):
    with history_reader() as store:
        value=store.get_binding(binding_id)
        if value is None or value['ownerKind']!='watch_event':raise EvidenceError('not_found',404)
        return {'ok':True,'event':value}
