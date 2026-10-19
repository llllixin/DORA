"""Read-only source and candidate endpoints; no publication writes over HTTP."""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal
from app.wiki.reader import read_cards
from app.wiki.candidates import CandidateService
from app.rag.contracts import RagContractError

router=APIRouter(prefix='/wiki')


def index_state():
    from app.rag.repository import RagRepository
    from app.rag.contracts import RagIndexUnavailable
    from app.repository import DataSourceUnavailableError
    from sqlalchemy.exc import SQLAlchemyError
    try: return RagRepository().index_status()
    except RagIndexUnavailable as exc:
        return {'indexStatus':'source_unavailable','reasonCode':exc.code}
    except (SQLAlchemyError,DataSourceUnavailableError):
        return {'indexStatus':'source_unavailable','reasonCode':'data_source_unavailable'}


def card_view(doc):
    gov=doc.get('governance') or {};review=gov.get('review')
    return {'id':doc['id'],'title':doc['title'],'version':doc['version'],'status':doc['status'],
            'legacy':doc.get('schema_version')!=2,'schemaVersion':doc.get('schema_version',1),
            'knowledgeType':doc['knowledge_type'],'content':doc['content'],'sourceType':doc['source_type'],
            'sourceRef':doc.get('source_ref'),'conceptIds':doc.get('concept_ids',[]),
            'wikiCard':{'cardType':doc['wiki_card']['card_type'],'sections':doc['wiki_card']['sections'],'conceptNote':doc['wiki_card']['concept_note']} if 'wiki_card' in doc else None,
            'governance':{'evidenceLevel':gov.get('evidence_level'),'applicability':gov.get('applicability'),
                          'unknowns':gov.get('unknowns',[]),'sourceRefs':gov.get('source_refs',[]),
                          'review':{'actor':review['actor'],'timestamp':review['timestamp'],'reason':review['reason'],'payloadHash':review['payload_hash'],'baseVersion':review['base_version'],'decision':review['decision']} if review else None}}


def candidate_view(row):
    return {'candidateId':row['candidate_id'],'entryType':row['entry_type'],'sourceId':row['source_id'],
            'sourcePayloadHash':row['source_payload_hash'],'revision':row['revision'],
            'candidateStatus':row['status'],'sourceAvailable':row['source_available'],'superseded':row['superseded'],
            'evidenceLevel':row['evidence_level'],'createdAt':row['created_at'],'card':card_view(row['payload']),
            'reviewEvents':row['review_events']}


def cards(document_id=None,version=None):
    try:return read_cards(document_id=document_id,version=version)
    except RagContractError as exc:raise HTTPException(status_code=503,detail='wiki source unavailable or invalid') from exc


def get_catalog_store():
    from app import db
    from app.rag.source import KnowledgeSource
    from app.wiki.catalog_store import CatalogStore
    return CatalogStore(db.get_engine(), KnowledgeSource())


@router.get('/catalog')
def catalog(q: str=Query(default='',max_length=300),
            knowledgeType: Literal['glossary','rule','procedure','case','external'] | None=None,
            offset: int=Query(default=0,ge=0),pageSize: int=Query(default=20,ge=1,le=25),
            includeSimulated: bool=False,expectedCatalogRevision: str | None=None,
            store=Depends(get_catalog_store)):
    from app.wiki.catalog import CatalogError, CatalogOptions, build_catalog
    try:
        options=CatalogOptions(q,knowledgeType,offset,pageSize,includeSimulated,expectedCatalogRevision)
        return build_catalog(store.capture(),options)
    except CatalogError as exc:
        raise HTTPException(status_code=exc.status_code,detail={'reasonCode':exc.code}) from exc


@router.get('/cards')
def list_cards():
    return {'ok':True,'cards':[card_view(d) for d in cards()],**index_state()}


@router.get('/cards/{document_id}')
def get_card(document_id:str,version:int|None=Query(default=None,ge=1)):
    rows=cards(document_id,version)
    if not rows:raise HTTPException(status_code=404,detail='wiki card not found')
    return {'ok':True,'card':card_view(rows[0]),**index_state()}


@router.get('/candidates')
def list_candidates():
    return {'ok':True,'candidates':[candidate_view(row) for row in CandidateService().list()]}


@router.get('/candidates/{candidate_id}')
def get_candidate(candidate_id:str):
    row=CandidateService().get(candidate_id)
    if row is None:raise HTTPException(status_code=404,detail='wiki candidate not found')
    return {'ok':True,'candidate':candidate_view(row)}
