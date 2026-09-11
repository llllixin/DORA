from pydantic import BaseModel


class InsightFactor(BaseModel):
    """判级/后果里的因子（name + value，值全部可回溯到引擎快照）。"""
    name: str
    value: str


class InsightSeverity(BaseModel):
    """洞察严重等级（引擎按快照显式计算；insight-judgment-structure）。"""
    level: str  # high | medium | low
    score: int
    rule: str
    drivers: list[InsightFactor]
    basis: str  # engine


class InsightConsequence(BaseModel):
    """洞察可能后果（引擎确定性外推；数字全部可回溯）。"""
    summary: str
    horizon: str
    condition: str
    impacts: list[InsightFactor]
    basis: str  # engine


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
    severity: InsightSeverity
    consequence: InsightConsequence


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


class StepExpertsRequest(BaseModel):
    """action-loop-timeline：整体设置某步负责专家（请求体即完整名单；空列表 = 清除）。"""
    experts: list[str] = []


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
