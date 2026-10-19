"""Offline replay of a frozen, same-space semantic snapshot; never makes network calls."""
from collections import Counter
from copy import deepcopy
import math
from types import SimpleNamespace
from app.rag.contracts import load_eval_set
from app.rag.identity import canonical,digest,profile_hash
from app.rag.indexer import split_text
from app.rag.ontology import Ontology
from app.rag.source import KnowledgeSource
from app.rag.repository import RagRepository
from app.rag.embeddings import cosine
from app.rag.retrieval import HybridRetriever,lexical_score
from app.rag.service import RagService
from app.rag.answer import TemplateAnswerProvider
from app.rag.evaluation import evaluate
from app.wiki.reader import effective_documents
from app.runtime.contracts import RuntimeFailure


class ReplayRuns:
    """Transient audit sink for offline evaluation, separate from persisted live runs."""
    def __init__(self):self.runs={}
    def create_agent_run(self,**kwargs):
        key='replay-'+str(len(self.runs)+1);self.runs[key]={'id':key,**kwargs};return self.runs[key]
    def append_agent_run_event(self,key,event):self.runs[key]['events'].append(event);return self.runs[key]
    def finish_agent_run(self,key,status,output):self.runs[key].update(status=status,output=output);return self.runs[key]


class FrozenProvider:
    external=False
    def __init__(self,profile,vectors):
        self.kind=profile['provider'];self.model=profile['model'];self.dimensions=profile['dimensions'];self.vectors=vectors
    def embed(self,texts):return [deepcopy(self.vectors[digest(t)]) for t in texts]


class FrozenCorpus:
    def __init__(self,chunks):self.chunks=chunks
    def active_chunks(self,types=None):return [deepcopy(c) for c in self.chunks if not types or c['knowledge_type'] in types]


class SemanticUnion(HybridRetriever):
    def __init__(self,*args,threshold,**kwargs):super().__init__(*args,**kwargs);self.threshold=threshold
    def search(self,query,top_k=5,knowledge_types=None,*,run_context=None):
        run_context.budget.check();expansion=self.ontology.expand(query)
        if expansion['semanticStatus']=='clarification_required':return {'query':query,'normalized':expansion,'empty':True,'hits':[]}
        vector=self.embedding_provider.embed([' '.join([query,*expansion['terms']])])[0]
        chunks=self.repository.active_chunks(knowledge_types);scores={};by_id={c['chunk_id']:c for c in chunks}
        for c in chunks:
            corpus=' '.join([c['title'],c['content'],*c['aliases'],*c['concept_ids']])
            lex=lexical_score(query,corpus)
            if set(expansion['concept_ids'])&set(c['concept_ids']):lex=min(1.,lex+.25)
            scores[c['chunk_id']]=(lex,max(0.,cosine(vector,c['embedding'])))
        ranks=[{cid:n for n,cid in enumerate(sorted((cid for cid,s in scores.items() if s[i]>0),key=lambda cid:(-scores[cid][i],cid)),1)} for i in (0,1)]
        fused=[(sum(1/(60+r[cid]) for r in ranks if cid in r),cid) for cid,s in scores.items() if s[0]>=.16 or s[1]>=self.threshold]
        hits=[]
        for score,cid in sorted(fused,key=lambda item:(-item[0],item[1]))[:top_k]:
            c={k:v for k,v in by_id[cid].items() if k!='embedding'}
            hits.append({**c,'score':round(score,6),'lexical_score':scores[cid][0],'vector_score':scores[cid][1],'retrieval':'semantic-union-offline'})
        run_context.budget.check();return {'query':query,'normalized':expansion,'empty':not hits,'hits':hits}


def compare_semantic_snapshot(snapshot=None):
    pending={'status':'not_executed','defaultPolicy':'lexical-gated-rrf-v1','candidateEligibleForDefault':False,
        'externalModelCalls':0,'actualTokens':None,'actualCost':None}
    if snapshot is None:return {**pending,'reason':'authorized same-space semantic snapshot not supplied'}
    try:
        profile=snapshot['embeddingProfile'];dimensions=profile['dimensions']
        if profile['provider']=='hash' or profile_hash(profile)!=snapshot['profileHash']:raise ValueError('space')
        if type(dimensions) is not int or dimensions<=0:raise ValueError('dimensions')
        source=KnowledgeSource().snapshot()
        if snapshot['sourceRevision']!=source.revision:raise ValueError('source revision')
        threshold=snapshot['semanticThreshold']
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<threshold<=1:raise ValueError('threshold')
        docs=effective_documents(source.documents,source.business_date);chunks=[];expected={}
        for doc in docs:
            if (doc.get('governance') or {}).get('origin'):raise ValueError('live origin proof required')
            for index,body in enumerate(split_text(doc['content'])):
                cid=f"{doc['id']}@{doc['version']}#{index}-{digest(body)[:12]}"
                expected[cid]=(doc,index,body,digest(doc['title']+'\n'+body))
        document_rows={c['chunk_id']:c for c in snapshot['documents']}
        queries={q['id']:q for q in snapshot['queries']};gold=load_eval_set('ontology-v2');ontology=Ontology.load()
        if len(document_rows)!=len(snapshot['documents']) or set(document_rows)!=set(expected):raise ValueError('document set')
        if len(queries)!=len(snapshot['queries']) or set(queries)!={q['id'] for q in gold}:raise ValueError('question set')
        def vector(row,wanted):
            v=row['vector']
            if row['profileHash']!=snapshot['profileHash'] or row['embeddingInputHash']!=wanted:raise ValueError('input space')
            if not isinstance(v,list) or len(v)!=dimensions or not all(type(x) in (int,float) and math.isfinite(x) for x in v):raise ValueError('vector')
            return v
        query_vectors={}
        for row in gold:
            query=' '.join([row['query'],*ontology.expand(row['query'])['terms']]);h=digest(query)
            query_vectors[h]=vector(queries[row['id']],h)
        for cid,(doc,index,body,h) in expected.items():
            c={'chunk_id':cid,'document_id':doc['id'],'version':doc['version'],'chunk_index':index,
                'title':doc['title'],'content':body,'knowledge_type':doc['knowledge_type'],
                'source_type':doc['source_type'],'source_ref':doc.get('source_ref',''),'source_url':doc.get('source_url',''),
                'metric_keys':doc['metric_keys'],'concept_ids':doc['concept_ids'],'aliases':doc['aliases'],
                'embedding_provider':profile['provider'],'embedding_model':profile['model'],
                'embedding':vector(document_rows[cid],h)}
            chunks.append(c)
    except (KeyError,ValueError,TypeError,AttributeError) as exc:raise RuntimeFailure('invalid_semantic_snapshot') from exc
    corpus=FrozenCorpus(chunks);provider=FrozenProvider(profile,query_vectors);reports={}
    class Observed(RagService):
        def __init__(self,*a,**kw):super().__init__(*a,**kw);self.chars=[]
        def answer(self,*a,**kw):
            result=super().answer(*a,**kw)
            if result['status']=='answered':self.chars.append(sum(len(c['content']) for c in result['retrieval']['hits']))
            return result
    for policy in ('lexical-gated-rrf-v1','semantic-union-candidate'):
        service=Observed(corpus,ReplayRuns(),provider,TemplateAnswerProvider())
        if policy=='semantic-union-candidate':service.retriever=SemanticUnion(corpus,provider,threshold=threshold)
        reports[policy]={}
        for evaluation_profile in ('legacy-v1','ontology-v2'):
            service.chars=[];report=evaluate(service,evaluation_profile)
            chars=sorted(service.chars);report['contextBodyChars']={'mean':sum(chars)/len(chars) if chars else 0,'p95':chars[math.ceil(len(chars)*.95)-1] if chars else 0}
            reports[policy][evaluation_profile]=report
    baseline=reports['lexical-gated-rrf-v1']['ontology-v2'];candidate=reports['semantic-union-candidate']['ontology-v2']
    eligible=(baseline['passed'] and candidate['passed'] and all(candidate['metrics'][k]>=baseline['metrics'][k] for k in ('recall_at_5','mrr')) and
        all(candidate['contextBodyChars'][k]<=baseline['contextBodyChars'][k] for k in ('mean','p95')))
    captured=((snapshot.get('provenance') or {}).get('kind')=='captured' and profile['provider'] in ('openai','local-semantic'))
    reports['semantic-union-candidate']['legacy-v1']['strategyProfile']='semantic-union-candidate'
    reports['semantic-union-candidate']['ontology-v2']['strategyProfile']='semantic-union-candidate'
    return {**pending,'status':'evaluated' if captured else 'synthetic_diagnostic_only','candidateEligibleForDefault':bool(eligible and captured),
        'reports':reports,'profileHash':snapshot['profileHash'],'sourceRevision':source.revision,
        'captureUsage':snapshot.get('captureUsage'),'note':'offline template replay, citation checks are not semantic answer correctness; default unchanged'}
