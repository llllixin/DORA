"""SQLAlchemy 数据模型：引擎原始数据与规则配置（C2 PostgreSQL Repository）。"""
from sqlalchemy import Column, Float, Integer, JSON, String, UniqueConstraint
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
