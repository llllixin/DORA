"""SQLAlchemy 数据模型：引擎原始数据与规则配置（C2 PostgreSQL Repository）。"""
from sqlalchemy import Column, Float, Integer, JSON, String, Text, UniqueConstraint
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
    """最近一次数据更新事件（按 updated_at 唯一去重）。"""
    __tablename__ = "data_update_log"
    __table_args__ = (UniqueConstraint("updated_at", name="uq_data_update"),)
    id = Column(Integer, primary_key=True)
    updated_at = Column(String(16), nullable=False)
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


class WatchTarget(Base):
    """持续关注委托（V4-T1）：一句话委托原文 + 解析结果 + 状态/频率。"""
    __tablename__ = "watch_target"
    id = Column(String(20), primary_key=True)  # w- + uuid4 hex[:12]
    raw_text = Column(String(500), nullable=False, default="")
    intent = Column(JSON, nullable=False, default=dict)  # {metric_key,dimension,condition,frequency}
    status = Column(String(16), nullable=False, default="watching")  # watching|paused
    frequency = Column(String(16), nullable=False, default="on_update")  # on_update|daily 09:00|weekly
    last_checked_at = Column(String(32), nullable=False, default="")
    last_event_at = Column(String(32), nullable=False, default="")
    created_at = Column(String(32), nullable=False, default="")


class WatchEvent(Base):
    """持续关注命中事件（V4-T1）：某次评估命中（change/escalate）的时点与前后值。"""
    __tablename__ = "watch_event"
    id = Column(Integer, primary_key=True)
    target_id = Column(String(20), nullable=False, index=True)
    triggered_at = Column(String(32), nullable=False, default="")
    kind = Column(String(16), nullable=False, default="change")  # change|escalate
    summary = Column(String(500), nullable=False, default="")
    values = Column(JSON, nullable=False, default=dict)  # {prev,cur,metric,dimension}


class ActionCase(Base):
    """行动档案（V5-T1）：一条档案 = 一个引擎判定的 problem/opportunity 洞察（id=insight_id）。"""
    __tablename__ = "action_case"
    id = Column(String(32), primary_key=True)  # insight_id（p1/o1/e2…）
    kind = Column(String(16), nullable=False, default="problem")  # problem|opportunity
    tag = Column(String(32), nullable=False, default="")
    tag_cls = Column(String(16), nullable=False, default="red")
    case_title = Column(String(200), nullable=False, default="")
    code = Column(String(32), nullable=False, default="")
    source = Column(String(200), nullable=False, default="")
    status = Column(String(16), nullable=False, default="open")  # open|running|waiting_verify|resolved
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
