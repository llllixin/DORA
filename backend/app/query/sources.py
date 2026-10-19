"""Frozen source adapters, explicit provenance and source-balanced fusion."""
from __future__ import annotations
from copy import deepcopy
import re
from app.query.contracts import seal_evidence,ReadPolicy,QueryConflict
from app.rag.contracts import RagIndexUnavailable,RagIndexConflict
from app.rag.identity import canonical,digest,document_key
from app.rag.snapshot import build_retrieval_snapshot
from app.rag.retrieval import HybridRetriever,lexical_score
from app.wiki.contracts import canonical_hash

SIMULATED={'simulated','sample','demo'}
def allowed_simulation(mode,options,policy):return mode not in SIMULATED or (options.includeSimulated and policy.allowSimulated)

def bounded_text(text,limit=3000):
    """Retain complete sentences/paragraphs only; never invent a clipped quote."""
    parts=re.findall(r'[^。！？\n]+[。！？\n]?|[。！？\n]',text or '')
    result=''
    for part in parts:
        if len(result)+len(part)>limit:break
        result+=part
    return result.strip()

def base_evidence(view,kind,*,source_type='project',mode='legacy_unknown',level='legacy_unknown',approval='unreviewed_record'):
    return dict(sourceKind=kind,scopeId='dora:default',sourceType=source_type,sourceMode=mode,evidenceLevel=level,
                approvalStatus=approval,subject={'metricKey':None,'dimension':None,'sourceScopeDescription':None},
                observedPeriod={'label':None,'isoDate':None},readAt=view.readAt,knowledgeType=None,archiveType=None,
                documentId=None,documentVersion=None,chunkId=None,archiveId=None,sourceId=None,sourceInstanceFingerprint=None,
                archiveVersion=None,snapshotId=None,occurrenceId=None,dataRevision=None,businessVersion=None,
                sourceRevision=None,indexBatchId=None,recordGroupId=None)

class FrozenWikiRepository:
    def __init__(self,view,options,policy):self.view=view;self.options=options;self.policy=policy
    def retrieval_snapshot(self,knowledge_types=None,*,budget=None,desired_profile=None,**kwargs):
        def predicate(doc):
            mode='simulated' if doc.get('source_type')=='simulated' or (doc.get('governance') or {}).get('evidence_level')=='simulated' else 'project'
            return allowed_simulation(mode,self.options,self.policy) and ('wiki' in self.options.sourceKinds) and ('wiki' in self.policy.allowedSourceKinds)
        return build_retrieval_snapshot(self.view.source,self.view.indexState,knowledge_types=knowledge_types or self.options.knowledgeTypes,
                                        desired_profile=desired_profile,budget=budget,document_predicate=predicate)
    def active_chunks(self,knowledge_types=None):return self.retrieval_snapshot(knowledge_types)['chunks']

def wiki_evidence(view,query,options,policy,*,run_context,embedding_provider):
    state=view.sourceStates.get('wiki',{'state':'excluded','reasonCode':'source_excluded'})
    if 'wiki' not in policy.allowedSourceKinds or 'wiki' not in options.sourceKinds:return {'evidence':[],'sourceState':{'state':'excluded','reasonCode':'source_excluded'},'index':None}
    if view.source is None or view.indexState is None:return {'evidence':[],'sourceState':state,'index':None}
    try:
        result=HybridRetriever(FrozenWikiRepository(view,options,policy),embedding_provider).search(query,options.topK,list(options.knowledgeTypes) or None,run_context=run_context)
    except RagIndexConflict as exc:
        raise QueryConflict(exc.code,run_id=run_context.run_id) from exc
    except RagIndexUnavailable as exc:
        return {'evidence':[],'sourceState':{'state':'unavailable','reasonCode':exc.code},'index':None}
    docs={document_key(d):d for d in view.source.documents};evidence=[]
    for hit in result['hits']:
        doc=docs[f"{hit['document_id']}@{hit['version']}"];governance=doc.get('governance') or {};origin=governance.get('origin') or {}
        level=governance.get('evidence_level') or 'legacy_unknown';stype=doc.get('source_type') or 'project'
        if stype=='simulated':level='simulated'
        text=bounded_text(hit['content'])
        if not text:continue
        e=base_evidence(view,'wiki',source_type=stype,mode='simulated' if level=='simulated' else 'project',level=level,approval='reviewed')
        e.update(knowledgeType=doc['knowledge_type'],documentId=doc['id'],documentVersion=doc['version'],chunkId=hit['chunk_id'],sourceRevision=view.source.revision,
                 indexBatchId=view.indexState['head'],data={'title':hit['title'],'text':text},sourceVersionHash=__import__('app.rag.identity',fromlist=['source_version_hash']).source_version_hash(doc),
                 sourceUrl=doc.get('source_url',''),score=hit['score'])
        if origin.get('snapshot'):
            snap=origin['snapshot'];e['recordGroupId']=digest(canonical([snap.get('entry_type'),snap.get('source_id'),snap.get('case_created_at')]))
        evidence.append(seal_evidence(e))
    index=result.get('index') or {};status='pending' if index.get('indexStatus')=='pending' else ('ready' if evidence else 'empty')
    return {'evidence':evidence,'sourceState':{'state':status,'reasonCode':result.get('fallbackReason'),'returnedCount':len(evidence),**index},'index':index,
            'fallbackReason':result.get('fallbackReason')}

def archive_evidence(view,query,options,policy,*,run_context):
    if 'archive' not in options.sourceKinds or 'archive' not in policy.allowedSourceKinds:return {'evidence':[],'sourceState':{'state':'excluded','reasonCode':'source_excluded'},'index':None}
    origin=view.archiveOrigins;candidates=origin.get('candidates',[]);cases={c['id']:c for c in origin.get('cases',[])};ranked=[];excluded=0
    for archive in view.archives:
        run_context.budget.check()
        if options.archiveTypes and archive['entry_type'] not in options.archiveTypes:continue
        if options.knowledgeTypes and 'case' not in options.knowledgeTypes:continue
        related=[c for c in candidates if c['source_id']==archive['source_id'] and c['entry_type']==archive['entry_type']]
        proofs=[];deleted=False;known_simulation=False
        case=cases.get(archive['source_id'])
        for candidate in related:
            snap=((candidate.get('payload') or {}).get('governance') or {}).get('origin',{}).get('snapshot') or {}
            exact=all(snap.get(k)==archive.get(k) for k in ('entry_type','source_id','code','title','content','note','created_at'))
            removed=any(ev.get('eventType')=='source_deleted' for ev in candidate.get('review_events',[]))
            known_simulation|=candidate['evidence_level']=='simulated' and exact
            deleted|=removed and exact
            if exact and case and case['created_at']==snap.get('case_created_at') and case['origin']==snap.get('case_origin') and case['status']=='resolved' and not removed:
                if canonical_hash(snap)==candidate['source_payload_hash']:proofs.append((candidate,snap))
        if deleted and not proofs:excluded+=1;continue
        known_simulation|=bool(case and case.get('origin')=='demo')
        mode='simulated' if known_simulation else ('reported' if proofs else 'legacy_unknown')
        if not allowed_simulation(mode,options,policy):excluded+=1;continue
        corpus='\n'.join([archive['title'],archive['content'],archive['note']]);score=lexical_score(query,corpus)
        if score<.16:continue
        text=bounded_text('\n'.join([archive['content'],archive['note']]))
        if not text:continue
        e=base_evidence(view,'archive',source_type='simulated' if mode=='simulated' else 'project',mode=mode,level=mode)
        e.update(knowledgeType='case',archiveType=archive['entry_type'],archiveId=archive['id'],sourceId=archive['source_id'],archiveCode=archive['code'],
                 data={'title':archive['title'],'text':text},archiveObservationHash=digest(canonical(archive)),score=score)
        if proofs:
            candidate,snap=max(proofs,key=lambda p:p[0]['revision'])
            e['sourceInstanceFingerprint']=digest(canonical([archive['source_id'],snap['case_created_at']]))
            e['recordGroupId']=digest(canonical([archive['entry_type'],archive['source_id'],snap['case_created_at']]))
        ranked.append(seal_evidence(e))
    ranked.sort(key=lambda e:(-e['score'],e['evidenceId']))
    return {'evidence':ranked[:options.topK],'sourceState':{'state':'ready' if ranked else ('excluded' if excluded else 'empty'),
             'reasonCode':'simulated_or_deleted_source_excluded' if excluded and not ranked else None,'returnedCount':min(len(ranked),options.topK)},'index':None}

def fuse_evidence(wiki,archives,*,top_k):
    candidates=[]
    for source in (wiki,archives):
        for rank,e in enumerate(source,1):candidates.append((1/(60+rank),deepcopy(e)))
    candidates.sort(key=lambda v:(-v[0],v[1]['evidenceId']));chosen=[];groups=set();ids=set()
    def add(e):
        group=e.get('recordGroupId')
        if e['evidenceId'] in ids or (group and group in groups):return False
        chosen.append(e);ids.add(e['evidenceId'])
        if group:groups.add(group)
        return True
    if top_k>=2 and wiki and archives:
        add(wiki[0])
        for e in archives:
            if add(e):break
    for _,e in candidates:
        if len(chosen)>=top_k:break
        add(e)
    return chosen[:top_k]
