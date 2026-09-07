from pydantic import BaseModel


class InsightSummary(BaseModel):
    id: str
    type: str
    tag: str
    title: str
    desc: str
    confidence: float
    metric: str
    delta: str
    source: str
    question: str


class Pulse(BaseModel):
    problems: int
    opportunities: int
    changes: int
    watching: int
    last_updated: str


class EvidenceModel(BaseModel):
    id: str
    title: str
    source: str
    updated: str
    sheet: str
    scope: str
    metric: str
    hits: list[str]
    rows: str
    path: str
    fact: str
    judgment: str
    suggestion: str
    rawRows: list[list[str]]


class ActionStep(BaseModel):
    title: str
    desc: str
    evidence: str


class ActionCurrent(BaseModel):
    title: str
    desc: str
    why: str
    evidence: str


class ActionCaseModel(BaseModel):
    id: str
    kind: str
    tag: str
    tagCls: str
    caseTitle: str
    code: str
    source: str
    steps: list[ActionStep]
    current: ActionCurrent
    experts: list[str]
    data: list[str]
    expertDesc: str
    archive: str


class WatchItem(BaseModel):
    id: str
    name: str
    value: str
    color: str
    logic: str
    source: str


class WatchParseRequest(BaseModel):
    text: str
