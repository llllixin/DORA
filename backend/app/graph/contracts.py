"""Finite graph identities, read requests and shared admission budget."""
from copy import deepcopy
from dataclasses import dataclass
import re
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator
from sqlalchemy import text
from app.business_version import canonical_hash, SCOPE_ID


class GraphError(Exception):
    def __init__(self, code, status_code=503):
        super().__init__(code)
        self.code, self.status_code = code, status_code


def identity(kind, data):
    try: return 'g-' + kind + '-v1:' + canonical_hash(data)
    except (ValueError, TypeError, OverflowError) as exc:
        raise GraphError('graph_integrity_conflict', 409) from exc


def seal(kind, data):
    value = deepcopy(data)
    value['id'] = identity(kind, data)
    return value


def validate(kind, record):
    if record.get('id') != identity(kind, {k:v for k,v in record.items() if k != 'id'}):
        raise GraphError('graph_integrity_conflict', 409)


def graph_revision(graph):
    members={kind:sorted(r['id'] for r in graph[name]) for kind,name in
             [('entity','nodes'),('relation','relations'),('evidence','evidence')]}
    return manifest_revision(dict(members=members,sourceVector=graph['sourceVector'],missingEvidence=graph['missingEvidence']))


def manifest_revision(manifest):
    return 'graph-v1:'+canonical_hash(manifest)


def resolve_pointer(data, pointer):
    if not isinstance(pointer, str) or len(pointer) > 512 or (pointer and not pointer.startswith('/')):
        raise GraphError('graph_integrity_conflict', 409)
    value = data
    try:
        for raw in pointer.split('/')[1:] if pointer else []:
            if re.search(r'~[^01]|~$', raw): raise ValueError('escape')
            key = raw.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                if not re.fullmatch(r'0|[1-9][0-9]{0,5}', key): raise ValueError('index')
                value = value[int(key)]
            elif isinstance(value, dict): value = value[key]
            else: raise ValueError('not data')
        return deepcopy(value)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise GraphError('graph_integrity_conflict', 409) from exc


@dataclass(frozen=True)
class GraphLimits:
    buildAdmissionMs: int = 10000
    maxSnapshots: int = 100
    maxSourceBytes: int = 16777216
    maxSourceRows: int = 10000
    maxBuildNodes: int = 10000
    maxBuildRelations: int = 20000
    maxBuildWitnesses: int = 50000
    queryAdmissionMs: int = 2000
    maxHops: int = 2
    maxScannedRelations: int = 1000
    maxResultNodes: int = 100
    maxResultRelations: int = 200
    maxResultBytes: int = 65536


class Budget:
    def __init__(self, milliseconds=10000, *, clock=None):
        self.clock = clock or time.monotonic
        self.end = self.clock() + milliseconds / 1000
    def remaining(self): return max(0, self.end - self.clock())
    def check(self):
        if self.remaining() <= 0: raise GraphError('graph_deadline', 503)
    def prepare(self, session):
        from app.db_budget import prepare_session
        prepare_session(session,self)


class GraphRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entityId: StrictStr = Field(min_length=1, max_length=160)
    mode: Literal['current', 'historical'] = 'current'
    batchId: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    expectedGraphRevision: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    relationTypes: list[StrictStr] = Field(default_factory=list, max_length=13)
    direction: Literal['out', 'in', 'both'] = 'out'
    maxHops: StrictInt = Field(default=1, ge=1, le=2)
    maxNodes: StrictInt = Field(default=100, ge=1, le=100)
    maxRelations: StrictInt = Field(default=200, ge=1, le=200)
    includeSimulated: StrictBool = False
    @model_validator(mode='after')
    def policy(self):
        from app.graph.registry import REGISTRY
        if (self.mode == 'historical') != (self.batchId is not None):
            raise ValueError('historical mode requires batchId; current forbids batchId')
        if any(r not in REGISTRY for r in self.relationTypes): raise ValueError('unregistered relation')
        self.relationTypes = list(dict.fromkeys(self.relationTypes))
        return self
