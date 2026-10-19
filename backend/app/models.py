"""SQLAlchemy 数据模型：引擎原始数据与规则配置（C2 PostgreSQL Repository）。"""
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, JSON, String, Text, UniqueConstraint, ForeignKey
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class MetricSeries(Base):
    """时间序列原始数据（指标 key / 标签 / 维度 / 数值 / 单位）。"""
    __tablename__ = "metric_series"
    __table_args__ = (UniqueConstraint("metric_key", "label", "dimension", name="uq_metric_series"),)
    id = Column(Integer, primary_key=True)
    metric_key = Column(String(64), nullable=False, index=True)
    label = Column(String(32), nullable=False)
    dimension = Column(String(32), nullable=False, default="")
    value = Column(Float, nullable=False)
    unit = Column(String(16), nullable=False, default="")


class StoreClusterStore(Base):
    """Top 高客单门店行（用于集群检测聚合）。"""
    __tablename__ = "store_cluster_store"
    id = Column(Integer, primary_key=True)
    store = Column(String(32), nullable=False, unique=True)
    region = Column(String(16), nullable=False)
    aov = Column(Float, nullable=False)


class DataUpdateLog(Base):
    """数据更新事件（独立 ID，时间仅供展示）。"""
    __tablename__ = "data_update_log"
    id = Column(Integer, primary_key=True)
    updated_at = Column(String(64), nullable=False)
    rows_added = Column(Integer, nullable=False)
    total_rows = Column(Integer, nullable=False)
    metrics = Column(JSON, nullable=False, default=list)


class RuleConfig(Base):
    """规则参数配置（key → 类型化 value）。"""
    __tablename__ = "rule_config"
    key = Column(String(64), primary_key=True)
    value = Column(String(256), nullable=False)
    value_type = Column(String(16), nullable=False, default="str")


class InsightReasoning(Base):
    """洞察解释语义缓存（V3-T2）。"""
    __tablename__ = "insight_reasoning"
    id = Column(Integer, primary_key=True)
    insight_id = Column(String(64), nullable=False, unique=True)
    semantics = Column(JSON, nullable=False, default=dict)
    provider = Column(String(16), nullable=False, default="template")
    generated_at = Column(String(32), nullable=False, default="")


class BusinessRevision(Base):
    """Server-owned current input epoch/generation; never reset with sample data."""
    __tablename__ = "business_revision"
    scope_id = Column(String(64), primary_key=True)
    source_epoch = Column(String(36), nullable=False)
    generation = Column(BigInteger, nullable=False, default=0)
    source_manifest = Column(JSON, nullable=False, default=dict)


class VersionedReasoning(Base):
    """Exact current version/context cache; legacy insight_id cache stays separate."""
    __tablename__ = "versioned_reasoning"
    cache_key = Column(String(64), primary_key=True)
    scope_id = Column(String(64), nullable=False, index=True)
    insight_type_id = Column(String(64), nullable=False)
    occurrence_id = Column(String(80), nullable=False)
    business_version = Column(JSON, nullable=False)
    input_hash = Column(String(64), nullable=False)
    semantics = Column(JSON, nullable=False)
    provider = Column(String(16), nullable=False)
    generated_at = Column(String(32), nullable=False)


class WatchTarget(Base):
    """持续关注委托（V4-T1）：一句话委托原文 + 解析结果 + 状态/频率。"""
    __tablename__ = "watch_target"
    id = Column(String(20), primary_key=True)  # w- + uuid4 hex[:12]
    history_instance_id = Column(String(32), nullable=True)
    raw_text = Column(String(500), nullable=False, default="")
    intent = Column(JSON, nullable=False, default=dict)  # {metric_key,dimension,condition,frequency}
    status = Column(String(16), nullable=False, default="watching")  # watching|paused|escalated（escalated=升级即移交终态，仅评估写路径产生）
    frequency = Column(String(16), nullable=False, default="on_update")  # on_update|daily 09:00|weekly
    last_checked_at = Column(String(32), nullable=False, default="")
    last_event_at = Column(String(32), nullable=False, default="")
    created_at = Column(String(32), nullable=False, default="")


class WatchEvent(Base):
    """持续关注命中事件（V4-T1）：某次评估命中（change/escalate）的时点与前后值。"""
    __tablename__ = "watch_event"
    id = Column(Integer, primary_key=True)
    history_event_id = Column(String(32), nullable=True, unique=True)
    target_id = Column(String(20), nullable=False, index=True)
    triggered_at = Column(String(32), nullable=False, default="")
    kind = Column(String(16), nullable=False, default="change")  # change|escalate
    summary = Column(String(500), nullable=False, default="")
    values = Column(JSON, nullable=False, default=dict)  # {prev,cur,metric,dimension}


class ActionCase(Base):
    """行动档案（V5-T1）：一条档案 = 一个引擎判定的 problem/opportunity 洞察（id=insight_id）。"""
    __tablename__ = "action_case"
    id = Column(String(32), primary_key=True)  # insight_id（p1/o1/e2…）
    history_instance_id = Column(String(32), nullable=True)
    kind = Column(String(16), nullable=False, default="problem")  # problem|opportunity
    tag = Column(String(32), nullable=False, default="")
    tag_cls = Column(String(16), nullable=False, default="red")
    case_title = Column(String(200), nullable=False, default="")
    code = Column(String(32), nullable=False, default="")
    source = Column(String(200), nullable=False, default="")
    status = Column(String(16), nullable=False, default="open")  # open|running|waiting_verify|resolved
    # action-demo-separation：来源标记 demo=静态演示集随种子建立 / engine=引擎建档或用户认领
    origin = Column(String(16), nullable=False, default="engine")  # demo|engine
    orchestration = Column(JSON, nullable=False, default=dict)  # {experts, data, expertDesc}
    archive = Column(Text, nullable=False, default="")  # A3：处理过程可超 500（多轮 continue/长 note）
    created_at = Column(String(32), nullable=False, default="")
    updated_at = Column(String(32), nullable=False, default="")


class ActionStep(Base):
    """行动步骤（V5-T1）：归属 case，按 seq 排序，携带执行/验证回填位。"""
    __tablename__ = "action_step"
    id = Column(Integer, primary_key=True)
    case_id = Column(String(32), nullable=False, index=True)
    seq = Column(Integer, nullable=False, default=0)
    title = Column(String(200), nullable=False, default="")
    desc = Column(String(500), nullable=False, default="")
    evidence = Column(String(300), nullable=False, default="")
    why = Column(String(500), nullable=False, default="")
    status = Column(String(16), nullable=False, default="pending")  # pending|in_progress|done|blocked
    note = Column(String(500), nullable=False, default="")
    result = Column(String(1000), nullable=False, default="")
    finished_at = Column(String(32), nullable=False, default="")
    # action-loop-timeline：该步负责专家（整体设置的幂等名单；空列表 = 未指定负责专家）
    experts = Column(JSON, nullable=False, default=list)


class CaseLesson(Base):
    """行动经验沉淀（迭代 36）：resolved 档案的确定性处理记录（case_id 幂等）。"""
    __tablename__ = "case_lesson"
    case_id = Column(String(32), primary_key=True)
    code = Column(String(32), nullable=False, default="")
    kind = Column(String(16), nullable=False, default="problem")
    title = Column(String(300), nullable=False, default="")
    archive = Column(Text, nullable=False, default="")      # 处理过程全文（可长）
    resolution = Column(Text, nullable=False, default="")    # 沉淀结论 note（可长）
    created_at = Column(String(32), nullable=False, default="")


class KnowledgeArchive(Base):
    """统一知识/归档库（迭代 38）：resolved 档案按类型 + 经验 lesson 自动入库。"""
    __tablename__ = "knowledge_archive"
    __table_args__ = (UniqueConstraint("entry_type", "source_id", name="uq_knowledge_source"),)
    id = Column(Integer, primary_key=True)
    entry_type = Column(String(16), nullable=False, index=True)  # problem|opportunity|change|lesson
    source_id = Column(String(48), nullable=False, default="")   # case_id / lesson case_id
    code = Column(String(32), nullable=False, default="")
    title = Column(String(300), nullable=False, default="")
    content = Column(Text, nullable=False, default="")   # 处理过程全文（可长）
    note = Column(Text, nullable=False, default="")       # 结论（可长）
    created_at = Column(String(32), nullable=False, default="")


class KnowledgeCandidate(Base):
    """Immutable candidate revisions; audit text is not a business-data snapshot."""
    __tablename__ = "knowledge_candidate"
    __table_args__ = (UniqueConstraint("entry_type", "source_id", "revision", name="uq_candidate_revision"),)
    candidate_id = Column(String(40), primary_key=True)
    entry_type = Column(String(16), nullable=False, index=True)
    source_id = Column(String(48), nullable=False, index=True)
    source_payload_hash = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    evidence_level = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    review_events = Column(JSON, nullable=False, default=list)
    created_at = Column(String(40), nullable=False)


class AgentRun(Base):
    """Agent 运行记录（agent-tool-layer，迭代 42）：轨迹可回放/审计（events 用 JSON 列存）。"""
    __tablename__ = "agent_run"
    id = Column(String(40), primary_key=True)      # r-<hex12>
    trigger = Column(String(32), nullable=False, default="manual")  # manual|chat|data_update|watch_tick
    status = Column(String(16), nullable=False, default="done")
    input = Column(JSON, nullable=False, default=dict)
    events = Column(JSON, nullable=False, default=list)
    output = Column(JSON, nullable=False, default=dict)
    created_at = Column(String(32), nullable=False, default="")
    updated_at = Column(String(32), nullable=False, default="")


class RagDocument(Base):
    """RAG 知识版本；pk=id@version，历史版本保留，active 标记当前有效版本。"""
    __tablename__ = "rag_document"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_rag_document_version"),)
    pk = Column(String(160), primary_key=True)
    document_id = Column(String(128), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    knowledge_type = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False)
    source_snapshot = Column(JSON, nullable=True)
    source_version_hash = Column(String(64), nullable=True)
    active = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(String(32), nullable=False, default="")
    updated_at = Column(String(32), nullable=False, default="")


class RagChunk(Base):
    """可重建的 RAG chunk；embedding 用 JSON 保存，存储实现可替换。"""
    __tablename__ = "rag_chunk"
    __table_args__ = (UniqueConstraint("document_pk", "chunk_index", name="uq_rag_chunk_position"),)
    chunk_id = Column(String(200), primary_key=True)
    document_pk = Column(String(160), nullable=False, index=True)
    document_id = Column(String(128), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False)
    embedding = Column(JSON, nullable=False, default=list)
    embedding_provider = Column(String(64), nullable=False)
    embedding_model = Column(String(128), nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)


class RagIndexProjection(Base):
    __tablename__ = 'rag_index_projection'
    __table_args__ = (UniqueConstraint('document_pk', 'profile_hash', name='uq_rag_projection_space'),)
    projection_id = Column(String(66), primary_key=True)
    document_pk = Column(String(160), nullable=False, index=True)
    source_version_hash = Column(String(64), nullable=False)
    profile_hash = Column(String(64), nullable=False)
    profile_json = Column(JSON, nullable=False)
    chunks_json = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False)


class RagIndexBatch(Base):
    __tablename__ = 'rag_index_batch'
    batch_id = Column(String(34), primary_key=True)
    source_revision = Column(String(64), nullable=False)
    profile_hash = Column(String(64), nullable=False)
    manifest_json = Column(JSON, nullable=False)
    report_json = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False)


class RagIndexState(Base):
    __tablename__ = 'rag_index_state'
    scope = Column(String(64), primary_key=True)
    head_batch_id = Column(String(34), nullable=True)
    revision = Column(Integer, nullable=False, default=0)


class EvidenceSnapshot(Base):
    __tablename__='evidence_snapshot'
    snapshot_id=Column(String(80),primary_key=True)
    scope_id=Column(String(96),nullable=False,index=True)
    fact_version=Column(JSON,nullable=False)
    payload=Column(JSON,nullable=False)
    payload_hash=Column(String(64),nullable=False)
    schema_version=Column(Integer,nullable=False)
    source_level=Column(String(32),nullable=False)
    captured_at=Column(String(40),nullable=False)


class InsightOccurrence(Base):
    __tablename__='insight_occurrence'
    occurrence_id=Column(String(80),primary_key=True)
    scope_id=Column(String(96),nullable=False,index=True)
    insight_type_id=Column(String(32),nullable=False)
    fact_identity=Column(JSON,nullable=False)
    judgment=Column(JSON,nullable=False)
    content_hash=Column(String(64),nullable=False)


class EvidenceBinding(Base):
    __tablename__='evidence_binding'
    __table_args__=(UniqueConstraint('owner_kind','owner_instance_id',name='uq_evidence_owner'),)
    binding_id=Column(String(32),primary_key=True)
    scope_id=Column(String(96),nullable=False,index=True)
    snapshot_id=Column(String(80),ForeignKey('evidence_snapshot.snapshot_id',ondelete='RESTRICT'),nullable=True)
    owner_kind=Column(String(32),nullable=False)
    owner_instance_id=Column(String(32),nullable=False)
    owner_public_id=Column(String(96),nullable=False)
    source_kind=Column(String(32),nullable=False)
    source_instance_id=Column(String(32),nullable=False,index=True)
    occurrence_id=Column(String(80),ForeignKey('insight_occurrence.occurrence_id',ondelete='RESTRICT'),nullable=True)
    capture_context=Column(JSON,nullable=False)
    source_record=Column(JSON,nullable=False)
    recorded_at=Column(String(40),nullable=False)


class ActionOccurrenceLink(Base):
    __tablename__='action_occurrence_link'
    scope_id=Column(String(96),primary_key=True)
    occurrence_id=Column(String(80),ForeignKey('insight_occurrence.occurrence_id',ondelete='RESTRICT'),primary_key=True)
    case_instance_id=Column(String(32),nullable=False,unique=True)
    case_public_id=Column(String(96),nullable=False)
    opening_binding_id=Column(String(32),ForeignKey('evidence_binding.binding_id',ondelete='RESTRICT'),nullable=False)


class ActionVerification(Base):
    __tablename__='action_verification'
    __table_args__=(UniqueConstraint('case_instance_id','seq',name='uq_evidence_verification_seq'),)
    verification_id=Column(String(32),primary_key=True)
    scope_id=Column(String(96),nullable=False,index=True)
    case_instance_id=Column(String(32),nullable=False,index=True)
    case_public_id=Column(String(96),nullable=False)
    seq=Column(Integer,nullable=False)
    outcome=Column(String(16),nullable=False)
    note=Column(Text,nullable=False)
    binding_id=Column(String(32),ForeignKey('evidence_binding.binding_id',ondelete='RESTRICT'),nullable=False)
    recorded_at=Column(String(40),nullable=False)


class EvidenceSourceEvent(Base):
    __tablename__='evidence_source_event'
    __table_args__=(UniqueConstraint('scope_id','source_kind','source_instance_id','event_type',name='uq_evidence_source_event'),)
    event_id=Column(String(32),primary_key=True)
    scope_id=Column(String(96),nullable=False,index=True)
    source_kind=Column(String(32),nullable=False)
    source_instance_id=Column(String(32),nullable=False,index=True)
    event_type=Column(String(16),nullable=False)
    recorded_at=Column(String(40),nullable=False)
