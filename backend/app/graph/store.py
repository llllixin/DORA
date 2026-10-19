"""Append-only graph content, complete batches and exact-head conditional commit."""
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select,func,or_,cast,Text
from app.business_version import SCOPE_ID,canonical_hash
from app.graph.contracts import GraphError,validate,graph_revision,manifest_revision
from app.graph.registry import check_relation
from app.graph.models import GraphEntity,GraphRelation,GraphRelationEvidence,GraphBuildBatch,GraphBuildMember,GraphState

KINDS={'entity':(GraphEntity,'entity_id','nodes'),'relation':(GraphRelation,'relation_id','relations'),
       'evidence':(GraphRelationEvidence,'evidence_id','evidence')}


def verify_graph(graph,budget=None):
    if budget:budget.check()
    if graph['graphRevision']!=graph_revision(graph):raise GraphError('graph_integrity_conflict',409)
    maps={}
    for kind,(_,_,name) in KINDS.items():
        maps[kind]={}
        for record in graph[name]:
            if budget:budget.check()
            validate(kind,record)
            if record['scopeId']!=SCOPE_ID or record['id'] in maps[kind]:raise GraphError('graph_integrity_conflict',409)
            maps[kind][record['id']]=record
    for edge in maps['relation'].values():
        if budget:budget.check()
        if edge['from'] not in maps['entity'] or edge['to'] not in maps['entity']:raise GraphError('graph_integrity_conflict',409)
        check_relation(edge['type'],maps['entity'][edge['from']]['type'],maps['entity'][edge['to']]['type'])
    covered=set()
    for evidence in maps['evidence'].values():
        if budget:budget.check()
        edge=maps['relation'].get(evidence['relationId'])
        if not edge or evidence['assertion']!={k:edge[k] for k in ('from','type','to')}:raise GraphError('graph_integrity_conflict',409)
        covered.add(edge['id'])
    if covered!=set(maps['relation']):raise GraphError('graph_integrity_conflict',409)
    if budget:budget.check()


class GraphStore:
    def __init__(self,limits):self.limits=limits
    def head(self,session):
        state=session.get(GraphState,SCOPE_ID)
        return state.head_batch_id if state else None
    def read_metadata(self,session,batch_id=None,*,budget):
        budget.prepare(session);batch_id=batch_id or self.head(session)
        if not batch_id:return None
        row=session.get(GraphBuildBatch,(SCOPE_ID,batch_id))
        if row is None:raise GraphError('unknown_or_out_of_scope_batch',404)
        manifest=deepcopy(row.manifest)
        caps={'entity':self.limits.maxBuildNodes,'relation':self.limits.maxBuildRelations,'evidence':self.limits.maxBuildWitnesses}
        if not isinstance(manifest,dict) or not {'members','sourceVector','missingEvidence'}==set(manifest):raise GraphError('graph_integrity_unavailable')
        if not isinstance(manifest['members'],dict) or set(manifest['members'])!=set(KINDS):raise GraphError('graph_integrity_unavailable')
        sets={}
        for kind,cap in caps.items():
            budget.check();ids=manifest['members'].get(kind)
            if not isinstance(ids,list) or len(ids)>cap or not all(isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise GraphError('graph_integrity_unavailable')
            sets[kind]=set(ids)
        if row.graph_revision!=manifest_revision(manifest):raise GraphError('graph_integrity_unavailable')
        # Membership is the read boundary: inner joins used by finite queries must
        # not hide a missing member or content row under the frozen revision.
        query=select(GraphBuildMember.item_kind,GraphBuildMember.item_id,
                     *(getattr(model,column) for model,column,_ in KINDS.values())).select_from(GraphBuildMember)
        for kind,(model,column,_) in KINDS.items():
            query=query.outerjoin(model,(GraphBuildMember.scope_id==model.scope_id)&
                (GraphBuildMember.item_kind==kind)&(GraphBuildMember.item_id==getattr(model,column)))
        query=query.where(GraphBuildMember.scope_id==SCOPE_ID,GraphBuildMember.batch_id==batch_id)
        query=query.order_by(GraphBuildMember.item_kind,GraphBuildMember.item_id).limit(sum(map(len,sets.values()))+1)
        found={kind:set() for kind in KINDS};positions={kind:index for index,kind in enumerate(KINDS)}
        budget.prepare(session)
        for kind,item_id,*content_ids in session.execute(query):
            budget.check()
            if kind not in sets or item_id not in sets[kind] or content_ids[positions[kind]]!=item_id:
                raise GraphError('graph_integrity_unavailable')
            found[kind].add(item_id)
        if found!=sets:raise GraphError('graph_integrity_unavailable')
        budget.check()
        return dict(batchId=batch_id,graph={**manifest,'graphRevision':row.graph_revision},memberSets=sets)

    def item(self,session,batch,kind,item_id,budget):
        if item_id not in batch['memberSets'][kind]:raise GraphError('unknown_or_out_of_scope_entity',404)
        model,column,_=KINDS[kind];budget.prepare(session)
        record=session.scalar(select(model.data).join(GraphBuildMember,
            (GraphBuildMember.scope_id==model.scope_id)&(GraphBuildMember.item_id==getattr(model,column)))
            .where(model.scope_id==SCOPE_ID,getattr(model,column)==item_id,GraphBuildMember.batch_id==batch['batchId'],
                   GraphBuildMember.item_kind==kind))
        if record is None:raise GraphError('graph_integrity_unavailable')
        validate(kind,record)
        if record.get('scopeId')!=SCOPE_ID or record.get('id')!=item_id:raise GraphError('graph_integrity_unavailable')
        budget.check();return deepcopy(record)

    def adjacent(self,session,batch,vertex,request,remaining,budget,seen):
        budget.prepare(session)
        conditions=[]
        if request.direction in {'out','both'}:conditions.append(GraphRelation.from_id==vertex)
        if request.direction in {'in','both'}:conditions.append(GraphRelation.to_id==vertex)
        query=select(GraphRelation.relation_id).join(GraphBuildMember,
            (GraphBuildMember.scope_id==GraphRelation.scope_id)&(GraphBuildMember.item_id==GraphRelation.relation_id))
        query=query.where(GraphRelation.scope_id==SCOPE_ID,GraphBuildMember.batch_id==batch['batchId'],
                          GraphBuildMember.item_kind=='relation',or_(*conditions))
        if seen:query=query.where(GraphRelation.relation_id.not_in(seen))
        if request.relationTypes:query=query.where(GraphRelation.data['type'].as_string().in_(request.relationTypes))
        result=session.scalars(query.order_by(GraphRelation.relation_id).limit(max(0,remaining)+1)).all()
        budget.check();return result

    def proofs(self,session,batch,relation_id,budget,*,max_rows,max_bytes):
        budget.prepare(session)
        metadata=session.execute(select(GraphRelationEvidence.evidence_id,func.length(cast(GraphRelationEvidence.data,Text)))
            .join(GraphBuildMember,(GraphBuildMember.scope_id==GraphRelationEvidence.scope_id)&
                  (GraphBuildMember.item_id==GraphRelationEvidence.evidence_id))
            .where(GraphRelationEvidence.scope_id==SCOPE_ID,GraphRelationEvidence.relation_id==relation_id,
                   GraphBuildMember.batch_id==batch['batchId'],GraphBuildMember.item_kind=='evidence')
            .order_by(GraphRelationEvidence.evidence_id).limit(max_rows+1)).all()
        values=[];size=0;limited=None
        for eid,length in metadata:
            budget.check()
            if len(values)>=max_rows:limited='evidence_rows';break
            if size+length>max_bytes:limited='result_bytes';break
            value=self.item(session,batch,'evidence',eid,budget)
            if value['relationId']!=relation_id:raise GraphError('graph_integrity_unavailable')
            values.append(value);size+=length
        return values,limited
    def read_batch(self,session,batch_id=None,*,budget):
        budget.prepare(session)
        batch_id=batch_id or self.head(session)
        if not batch_id:return None
        row=session.get(GraphBuildBatch,(SCOPE_ID,batch_id))
        if not row:raise GraphError('unknown_or_out_of_scope_batch',404)
        graph={k:deepcopy(v) for k,v in row.manifest.items() if k!='members'}
        max_counts={'entity':self.limits.maxBuildNodes,'relation':self.limits.maxBuildRelations,'evidence':self.limits.maxBuildWitnesses}
        for kind,(model,id_column,name) in KINDS.items():
            budget.prepare(session)
            query=select(GraphBuildMember.item_id).where(GraphBuildMember.scope_id==SCOPE_ID,
                GraphBuildMember.batch_id==batch_id,GraphBuildMember.item_kind==kind)
            count=session.scalar(select(func.count()).select_from(query.subquery()))
            if count>max_counts[kind]:raise GraphError('graph_integrity_unavailable')
            rows=session.execute(select(model.data).join(GraphBuildMember,
                (GraphBuildMember.scope_id==model.scope_id)&(GraphBuildMember.item_id==getattr(model,id_column)))
                .where(GraphBuildMember.scope_id==SCOPE_ID,GraphBuildMember.batch_id==batch_id,
                       GraphBuildMember.item_kind==kind).order_by(getattr(model,id_column)).limit(max_counts[kind]+1)).scalars()
            graph[name]=[]
            for value in rows:
                budget.check();graph[name].append(deepcopy(value))
            if len(graph[name])!=count:raise GraphError('graph_integrity_unavailable')
        graph['graphRevision']=row.graph_revision
        verify_graph(graph,budget)
        # The payload digest alone cannot detect an unrecognized member kind.
        self.read_metadata(session,batch_id,budget=budget)
        return dict(batchId=batch_id,graph=graph)

    def commit(self,session,graph,*,expected_head,budget):
        verify_graph(graph,budget);budget.prepare(session)
        state=session.scalar(select(GraphState).where(GraphState.scope_id==SCOPE_ID).with_for_update())
        current=state.head_batch_id if state else None
        if current!=expected_head:raise GraphError('head_changed',409)
        previous=self.read_batch(session,current,budget=budget) if current else None
        if previous and previous['graph']['graphRevision']==graph['graphRevision']:
            return dict(batchId=current,graphRevision=graph['graphRevision'],unchanged=True)
        for kind,(model,attr,name) in KINDS.items():
            for record in graph[name]:
                budget.check()
                old=session.get(model,(SCOPE_ID,record['id']))
                if old is not None:
                    if old.data!=record:raise GraphError('graph_integrity_conflict',409)
                    continue
                values=dict(scope_id=SCOPE_ID,**{attr:record['id']},data=deepcopy(record))
                if kind=='relation':values.update(from_id=record['from'],to_id=record['to'])
                if kind=='evidence':values['relation_id']=record['relationId']
                session.add(model(**values))
            session.flush();budget.prepare(session)
        batch_id='gb-'+uuid4().hex
        manifest={k:deepcopy(v) for k,v in graph.items() if k not in ('nodes','relations','evidence','graphRevision')}
        manifest['members']={kind:[r['id'] for r in graph[name]] for kind,(_,_,name) in KINDS.items()}
        session.add(GraphBuildBatch(scope_id=SCOPE_ID,batch_id=batch_id,graph_revision=graph['graphRevision'],
            manifest=manifest,created_at=datetime.now(timezone.utc).isoformat()))
        session.flush()
        for kind,(_,_,name) in KINDS.items():
            for record in graph[name]:session.add(GraphBuildMember(scope_id=SCOPE_ID,batch_id=batch_id,item_kind=kind,item_id=record['id']))
        session.flush()
        if state is None:state=GraphState(scope_id=SCOPE_ID);session.add(state)
        state.head_batch_id=batch_id
        session.flush();budget.check()
        return dict(batchId=batch_id,graphRevision=graph['graphRevision'],unchanged=False)
