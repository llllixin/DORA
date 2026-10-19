"""Finite public query contracts and server-owned read policy."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from app.rag.identity import canonical, digest
from app.runtime.contracts import RuntimeFailure

CONTRACT_VERSION='unified-query-v1-candidate'
SourceKind=Literal['wiki','archive']
KnowledgeType=Literal['glossary','rule','procedure','case','external']
ArchiveType=Literal['problem','opportunity','change','lesson']

@dataclass(frozen=True)
class QueryOptions:
    topK:int=5
    sourceKinds:tuple=('wiki','archive')
    knowledgeTypes:tuple=()
    archiveTypes:tuple=()
    includeSimulated:bool=False
    expectedDataRevision:str|None=None
    expectedSourceRevision:str|None=None

class CommonRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    topK:StrictInt=Field(default=5,ge=1,le=10)
    sourceKinds:list[SourceKind]=Field(default_factory=lambda:['wiki','archive'],min_length=1)
    knowledgeTypes:list[KnowledgeType]=Field(default_factory=list)
    archiveTypes:list[ArchiveType]=Field(default_factory=list)
    includeSimulated:StrictBool=False
    @field_validator('sourceKinds','knowledgeTypes','archiveTypes')
    @classmethod
    def unique(cls,value):return list(dict.fromkeys(value))
    def options(self):
        return QueryOptions(self.topK,tuple(self.sourceKinds),tuple(self.knowledgeTypes),tuple(self.archiveTypes),
                            self.includeSimulated,getattr(self,'expectedDataRevision',None),getattr(self,'expectedSourceRevision',None))
    @field_validator('query','question',check_fields=False)
    @classmethod
    def text(cls,value):
        value=value.strip()
        if not 1<=len(value)<=300:raise ValueError('text must contain 1..300 characters')
        return value

class QuerySearchRequest(CommonRequest):query:StrictStr
class QueryAnswerRequest(CommonRequest):
    question:StrictStr
    expectedDataRevision:StrictStr|None=Field(default=None,min_length=1,max_length=128)
    expectedSourceRevision:StrictStr|None=Field(default=None,min_length=1,max_length=128)

@dataclass(frozen=True)
class ReadPolicy:
    scopeId:str='dora:default'
    allowedSourceKinds:frozenset=frozenset({'wiki','archive','business'})
    allowSimulated:bool=True

@dataclass(frozen=True)
class ReadLimits:
    maxContextChunks:int=10
    maxContextChars:int=16384
    maxRequestBytes:int=24576
    maxReadViewRows:int=10000
    maxReadViewBytes:int=2097152
    maxResultBytes:int=65536
    maxMetricRows:int=200
    maxReadStatementMs:int=5000

def effective_limits(run_context):
    p=run_context.effective_profile
    return ReadLimits(**{k:min(v,getattr(p,k,v)) for k,v in vars(ReadLimits()).items()})

class QueryError(RuntimeFailure):
    status_code=500
    def __init__(self,code,*,run_id=None):super().__init__(code);self.code=code;self.run_id=run_id
class QueryConflict(QueryError):status_code=409
class QueryUnavailable(QueryError):status_code=503
class QueryEvidenceNotFound(QueryError):status_code=404
class QueryInvalid(QueryError):status_code=422

IDENTITY_IGNORED={'evidenceId','score','runId','readAt','uploadedAt','rank','citation','rrfScore'}
def evidence_id(evidence):return 'ev-v1:'+digest(canonical({k:v for k,v in evidence.items() if k not in IDENTITY_IGNORED}))
def validate_evidence(evidence):
    if evidence.get('evidenceId')!=evidence_id(evidence):raise QueryConflict('evidence_integrity_conflict')
    if evidence.get('contentHash')!=digest(canonical(evidence.get('data'))):raise QueryConflict('evidence_integrity_conflict')

def seal_evidence(evidence):
    value=deepcopy(evidence);value['contentHash']=digest(canonical(value.get('data')))
    value['evidenceId']=evidence_id(value);return value

# Paths are data-only fields. No arbitrary Python objects or attributes are traversed.
PATH_FIELDS={'data','rows','value','label','dimension','unit','text','title','metricKey','subject','observedPeriod','isoDate','sourceScopeDescription','content'}
def resolve_field(evidence,path):
    if not isinstance(path,str) or len(path)>160:raise ValueError('invalid field path')
    value=evidence
    for segment in path.split('.'):
        match=re.fullmatch(r'([A-Za-z][A-Za-z0-9]*)(?:\[([0-9]{1,3})\])?',segment)
        if not match or match[1] not in PATH_FIELDS or not isinstance(value,dict) or match[1] not in value:raise ValueError('invalid field path')
        value=value[match[1]]
        if match[2] is not None:
            index=int(match[2])
            if not isinstance(value,list) or index>=len(value):raise ValueError('invalid field path')
            value=value[index]
    return deepcopy(value)
