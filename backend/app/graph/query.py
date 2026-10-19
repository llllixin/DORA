"""Finite SQL neighborhoods over a content-addressed batch, with lazy provenance."""
from collections import Counter,deque
from copy import deepcopy
from app.business_version import canonical_hash
from app.graph.contracts import GraphError
from app.graph.registry import check_relation
from app.graph.source import byte_size
from app.graph.service import verify_witness


def envelope(batch,view,mode):
    graph=batch['graph']; vector=graph['sourceVector']
    return dict(status='ok',graphRevision=graph['graphRevision'],batchId=batch['batchId'],mode=mode,
        sourceState='in_sync' if vector==view['vector'] else 'pending',
        sourceVector=dict(hash=canonical_hash(vector),scopeId=vector['scopeId'],sourceRevision=vector['sourceRevision'],
                          effectiveDate=vector['effectiveDate'],graphSchemaHash=vector['graphSchemaHash']),
        nodes=[],relations=[],evidence=[],
        missingEvidence=[dict(reason=k,count=v) for k,v in sorted(Counter(m['reason'] for m in graph['missingEvidence']).items())],
        warnings=[],limitReason=None)


def visible_node(node,view,request):
    source=view['records'].get(node['sourceKey'])
    if source is None or node['sourceHash']!=source['hash']:raise GraphError('graph_integrity_unavailable')
    if not request.includeSimulated and ('simulated' in (node['sourceLevel'],source['level'])):return False
    return request.mode=='historical' or source['status']=='available'


def public_witness(witness,source):
    return {**deepcopy(witness),'evidenceId':witness['id'],'sourceCurrentStatus':source['status']}


def mark_limited(result,reason):
    result.update(status='limited',limitReason=reason)


def bounded_result(result,limits):
    if any(n['sourceLevel']=='simulated' for n in result['nodes']) or any(w['sourceLevel']=='simulated' for w in result['evidence']):
        result['warnings']=['simulated_sources']
    # The final status may add bytes after an edge has been admitted.
    while byte_size(result)>limits.maxResultBytes and result['relations']:
        removed=result['relations'].pop()['id'];result['evidence']=[w for w in result['evidence'] if w['relationId']!=removed]
        ids={e[k] for e in result['relations'] for k in ('from','to')}
        if result['nodes']:ids.add(result['nodes'][0]['id'])
        result['nodes']=[n for n in result['nodes'] if n['id'] in ids];mark_limited(result,'result_bytes')
    if byte_size(result)>limits.maxResultBytes:
        result.update(nodes=[],relations=[],evidence=[]);mark_limited(result,'result_bytes')
    if byte_size(result)>limits.maxResultBytes:result['missingEvidence']=[]
    if byte_size(result)>limits.maxResultBytes:raise GraphError('result_limit',422)
    return result


def edge_records(batch,view,request,edge_id,budget,max_rows,max_bytes):
    store,session=batch['store'],batch['session']
    edge=store.item(session,batch,'relation',edge_id,budget)
    nodes=[store.item(session,batch,'entity',eid,budget) for eid in dict.fromkeys((edge['from'],edge['to']))]
    check_relation(edge['type'],nodes[0]['type'],next(n['type'] for n in nodes if n['id']==edge['to']))
    if not all(visible_node(n,view,request) for n in nodes):return edge,nodes,[],None,0
    witnesses,limited=store.proofs(session,batch,edge_id,budget,max_rows=max_rows,max_bytes=max_bytes)
    if not witnesses and limited is None:raise GraphError('graph_integrity_unavailable')
    proofs=[]
    for witness in witnesses:
        budget.check()
        if witness['assertion']!={k:edge[k] for k in ('from','type','to')}:raise GraphError('graph_integrity_unavailable')
        source=verify_witness(witness,view)
        if not request.includeSimulated and 'simulated' in (witness['sourceLevel'],source['level']):continue
        if request.mode=='current' and source['status']!='available':continue
        proofs.append(public_witness(witness,source))
    budget.check();return edge,nodes,proofs,limited,len(witnesses)


def traversal(batch,view,request,limits,budget):
    graph=batch['graph']
    if request.expectedGraphRevision and request.expectedGraphRevision!=graph['graphRevision']:
        raise GraphError('graph_revision_conflict',409)
    result=envelope(batch,view,request.mode);selected=set();seen=set();scanned=0;proof_rows=0
    store,session=batch['store'],batch['session']
    try:
        budget.check()
        root=store.item(session,batch,'entity',request.entityId,budget)
        if not visible_node(root,view,request):raise GraphError('unknown_or_out_of_scope_entity',404)
        result['nodes']=[root];selected.add(root['id']);queue=deque([(root['id'],0)])
        if byte_size(result)>limits.maxResultBytes:return bounded_result(result,limits)
        while queue:
            budget.check();vertex,depth=queue.popleft()
            if depth>=min(request.maxHops,limits.maxHops):continue
            candidates=store.adjacent(session,batch,vertex,request,limits.maxScannedRelations-scanned,budget,seen)
            for edge_id in candidates:
                budget.check()
                if scanned>=limits.maxScannedRelations:mark_limited(result,'scanned_relations');return bounded_result(result,limits)
                seen.add(edge_id);scanned+=1
                edge,nodes,proofs,reason,used=edge_records(batch,view,request,edge_id,budget,
                    limits.maxScannedRelations-proof_rows,limits.maxResultBytes-byte_size(result))
                proof_rows+=used
                # Never admit an edge with a truncated proof set or without verified endpoints.
                if reason:mark_limited(result,reason);return bounded_result(result,limits)
                if not proofs:continue
                extra=[n for n in nodes if n['id'] not in selected]
                if len(selected)+len(extra)>min(request.maxNodes,limits.maxResultNodes):mark_limited(result,'result_nodes');return bounded_result(result,limits)
                if len(result['relations'])>=min(request.maxRelations,limits.maxResultRelations):mark_limited(result,'result_relations');return bounded_result(result,limits)
                candidate={**result,'nodes':result['nodes']+extra,'relations':result['relations']+[edge],
                           'evidence':result['evidence']+proofs}
                if byte_size(candidate)>limits.maxResultBytes:mark_limited(result,'result_bytes');return bounded_result(result,limits)
                result=candidate
                for node in extra:selected.add(node['id']);queue.append((node['id'],depth+1))
        budget.check()
        if not result['relations']:result['status']='insufficient_provenance'
        result=bounded_result(result,limits);budget.check();return result
    except GraphError as exc:
        if exc.code!='graph_deadline':raise
        mark_limited(result,'deadline');return bounded_result(result,limits)


def relation_evidence(batch,view,request,relation_id,limits,budget):
    if relation_id not in batch['memberSets']['relation']:raise GraphError('unknown_or_out_of_scope_relation',404)
    result=envelope(batch,view,request.mode)
    try:
        edge,nodes,proofs,reason,_=edge_records(batch,view,request,relation_id,budget,
            limits.maxScannedRelations,limits.maxResultBytes-byte_size(result))
        if reason:mark_limited(result,reason)
        elif not proofs:raise GraphError('unknown_or_out_of_scope_relation',404)
        else:result.update(nodes=nodes,relations=[edge],evidence=proofs)
        result=bounded_result(result,limits);budget.check();return result
    except GraphError as exc:
        if exc.code!='graph_deadline':raise
        result.update(nodes=[],relations=[],evidence=[]);mark_limited(result,'deadline')
        return bounded_result(result,limits)
