"""Graph content and batch membership are independent of authoritative business rows."""
from sqlalchemy import Column, String, JSON, ForeignKeyConstraint, CheckConstraint
from app.models import Base


class GraphEntity(Base):
    __tablename__='graph_entity'
    scope_id=Column(String(96),primary_key=True)
    entity_id=Column(String(96),primary_key=True)
    data=Column(JSON,nullable=False)


class GraphRelation(Base):
    __tablename__='graph_relation'
    scope_id=Column(String(96),primary_key=True)
    relation_id=Column(String(96),primary_key=True)
    from_id=Column(String(96),nullable=False,index=True)
    to_id=Column(String(96),nullable=False,index=True)
    data=Column(JSON,nullable=False)
    __table_args__=(ForeignKeyConstraint(['scope_id','from_id'],['graph_entity.scope_id','graph_entity.entity_id']),
                    ForeignKeyConstraint(['scope_id','to_id'],['graph_entity.scope_id','graph_entity.entity_id']))


class GraphRelationEvidence(Base):
    __tablename__='graph_relation_evidence'
    scope_id=Column(String(96),primary_key=True)
    evidence_id=Column(String(96),primary_key=True)
    relation_id=Column(String(96),nullable=False,index=True)
    data=Column(JSON,nullable=False)
    __table_args__=(ForeignKeyConstraint(['scope_id','relation_id'],['graph_relation.scope_id','graph_relation.relation_id']),)


class GraphBuildBatch(Base):
    __tablename__='graph_build_batch'
    scope_id=Column(String(96),primary_key=True)
    batch_id=Column(String(40),primary_key=True)
    graph_revision=Column(String(96),nullable=False)
    manifest=Column(JSON,nullable=False)
    created_at=Column(String(40),nullable=False)


class GraphBuildMember(Base):
    __tablename__='graph_build_member'
    scope_id=Column(String(96),primary_key=True)
    batch_id=Column(String(40),primary_key=True)
    item_kind=Column(String(16),primary_key=True)
    item_id=Column(String(96),primary_key=True)
    __table_args__=(ForeignKeyConstraint(['scope_id','batch_id'],['graph_build_batch.scope_id','graph_build_batch.batch_id']),
                    CheckConstraint("item_kind IN ('entity','relation','evidence')"))


class GraphState(Base):
    __tablename__='graph_state'
    scope_id=Column(String(96),primary_key=True)
    head_batch_id=Column(String(40),nullable=True)
    __table_args__=(ForeignKeyConstraint(['scope_id','head_batch_id'],['graph_build_batch.scope_id','graph_build_batch.batch_id']),)
