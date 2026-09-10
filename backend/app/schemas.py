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


class WatchCreateRequest(BaseModel):
    text: str
    frequency: str | None = None


class WatchStatusRequest(BaseModel):
    status: str


class ActionCreateRequest(BaseModel):
    insight_id: str


class StepBodyRequest(BaseModel):
    note: str = ""
    result: str = ""


class VerifyRequest(BaseModel):
    outcome: str  # resolved|continue
    note: str = ""


class ArchiveLessonRequest(BaseModel):
    note: str = ""


# ---------- agent-tool-layer（迭代 42）：工具层 / 检索 / 运行记录 / 问答 ----------
class KnowledgeSearchRequest(BaseModel):
    query: str
    types: list[str] = []
    top_k: int = 5


class AgentRunCreateRequest(BaseModel):
    trigger: str = "manual"
    input: dict = {}
    events: list = []
    output: dict = {}


class AgentRunEventRequest(BaseModel):
    event: dict = {}


class ChatRequest(BaseModel):
    question: str
    page: str = "pulse"
    insight_id: str | None = None
    workspace: str = "门店经营"
