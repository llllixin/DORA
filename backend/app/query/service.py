"""Bounded read-only query orchestration sharing one parent runtime ledger."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from app.query.contracts import (CONTRACT_VERSION,ReadPolicy,QueryOptions,QueryAnswerRequest,QuerySearchRequest,
    QueryConflict,QueryUnavailable,QueryError,effective_limits)
from app.query.routing import classify_query,search_plan,QueryPlan
from app.query.sources import wiki_evidence,archive_evidence,fuse_evidence
from app.query.metrics import read_metric,metric_binding_for_tool
from app.runtime.executor import RunContext
from app.runtime.budget import load_profile
from app.runtime.contracts import RuntimeFailure

class QueryService:
    def __init__(self,reader,*,policy,ontology,embedding_provider,run_repository):
        self.reader=reader;self.policy=policy;self.ontology=ontology;self.embedding_provider=embedding_provider;self.run_repository=run_repository
    def _profile(self,route):return load_profile(route,getattr(self.embedding_provider,'external',False) is True)
    def _request(self,plan,options,*,route,run_context=None,tool_reserved=False,answer=False,metric=False,read_at=None,response_projection=None):
        own=run_context is None
        run=run_context or RunContext(route,profile=self._profile(route),external=getattr(self.embedding_provider,'external',False) is True,
                                      repository=self.run_repository,input_data={'query':plan.query,'contractVersion':CONTRACT_VERSION})
        scope=None;value={}
        try:
            with run.limit_scope(self._profile(route)) as scope:
                value=self.execute(plan,options,run_context=run,tool_reserved=tool_reserved,read_at=read_at)
                from app.query.rendering import build_claims,validate_claims,render_answer,pack_response
                claims=build_claims(plan,value,run_id=run.run_id) if answer else []
                validate_claims(claims,value['evidence'],plan=plan)
                missing=value['missingParts'];reason=value.get('reasonCode') or plan.reasonCode
                if plan.route=='clarify' or reason in ('ambiguous_source_rows','incomparable_periods'):status='clarification_required'
                elif reason in ('budget_exceeded','deadline_exceeded','read_view_limit','context_limit','response_too_large'):status='limited'
                elif missing and value['evidence']:status='partial'
                elif missing or not value['evidence']:status='abstained'
                else:status='answered'
                citations=[{'evidenceId':e['evidenceId'],'contentHash':e['contentHash'],
                            'claimIds':[c['claimId'] for c in claims if e['evidenceId'] in c['evidenceIds']],
                            'href':f"/api/query/runs/{run.run_id}/evidence/{e['evidenceId']}"} for e in value['evidence']]
                payload={**value,'ok':status=='answered' or (not answer and not value['evidence'] and not missing),
                         'contractVersion':CONTRACT_VERSION,'runId':run.run_id,'scopeId':self.policy.scopeId,'status':status,'route':plan.route,
                         'claims':claims,'citations':citations,'clarifications':list(plan.clarifications),'reasonCode':reason,
                         'queryLimits':scope.summary(),**run.diagnostics()}
                if answer:payload.update(question=plan.query,answer=render_answer(claims))
                else:payload.update(query=plan.query,empty=not value['evidence'],hits=deepcopy(value['evidence']),references=deepcopy(citations))
                if metric:
                    payload.update({k:v for k,v in value.get('metricResult',{}).items() if k!='evidence'})
                    payload.setdefault('rows',[]);payload['count']=len(payload['rows'])
                if response_projection is not None:payload=response_projection(payload)
                run.emit({'type':'query_validated','contractVersion':CONTRACT_VERSION,'evidenceCount':len(value['evidence']),'claimCount':len(claims)})
                run.budget.check()
                payload=pack_response(payload,run_context=run)
                run.budget.check()
                # Persist exact delivered packet for standalone evidence lookup.
                return run.finish(payload,'limited' if status=='limited' else 'done') if own else payload
        except QueryError as exc:
            exc.run_id=run.run_id
            if own and not run.finished:run.finish({'contractVersion':CONTRACT_VERSION,'reasonCode':getattr(exc,'code',getattr(exc,'category',None))},'failed')
            raise
        except RuntimeFailure as exc:
            from app.query.rendering import limitation_text
            # Reject all late facts; the bounded terminal diagnostic can still be
            # audited. This neither admits a provider call nor finishes a parent.
            payload={'ok':False,'contractVersion':CONTRACT_VERSION,'runId':run.run_id,'scopeId':self.policy.scopeId,
                     'status':'limited','route':plan.route,'readAt':value.get('readAt'),'evidence':[],'claims':[],'citations':[],
                     'sourceStates':value.get('sourceStates',[]),'missingParts':list(plan.parts),'reasonCode':exc.category,
                     'toolExecutions':value.get('toolExecutions',[]),'businessVersion':value.get('businessVersion'),
                     'sourceRevision':value.get('sourceRevision'),'indexBatchId':value.get('indexBatchId'),**run.diagnostics()}
            if answer:payload.update(question=plan.query,answer=limitation_text(exc.category))
            else:payload.update(query=plan.query,empty=True,hits=[],references=[])
            if metric:payload.update(rows=[],count=0,empty=True)
            if scope:payload['queryLimits']=scope.summary()
            run.emit({'type':'query_limited','reasonCode':exc.category})
            return run.finish(payload,'limited') if own else payload
        except Exception:
            if own and not run.finished:run.finish({'contractVersion':CONTRACT_VERSION,'reasonCode':'query_failed'},'failed')
            raise
    def search(self,request,*,run_context=None,tool_reserved=False,response_projection=None):
        stamp=self.reader.now();plan=search_plan(request,policy=self.policy,on_date=stamp.date())
        return self._request(plan,request.options(),route='unified-search',run_context=run_context,tool_reserved=tool_reserved,read_at=stamp,response_projection=response_projection)
    def answer(self,request,*,run_context=None):
        stamp=self.reader.now();plan=classify_query(request.question,self.ontology,on_date=stamp.date(),options=request.options(),policy=self.policy)
        return self._request(plan,request.options(),route='unified-answer',run_context=run_context,answer=True,read_at=stamp)
    def metric(self,metric_key,dimension,limit,*,run_context=None,tool_reserved=False):
        binding=metric_binding_for_tool(metric_key,dimension,self.ontology)
        stamp=self.reader.now()
        if binding:binding={**binding,'rowLimit':min(200,max(1,limit))}
        plan=QueryPlan(metric_key,'current',('current',),('query_metric',) if binding else (),binding,'latest',('business',),
                       reasonCode='unknown_metric' if binding is None else None,businessDate=stamp.date())
        return self._request(plan,QueryOptions(topK=1),route='unified-search',run_context=run_context,tool_reserved=tool_reserved,metric=True,read_at=stamp)
    def execute(self,plan,options,*,run_context,tool_reserved=False,read_at=None):
        run=run_context;view=None;tools=[];evidence=[];source_states={};missing=[];metric_result={};reason=plan.reasonCode
        if (plan.expectedDataRevision,plan.expectedSourceRevision)!=(options.expectedDataRevision,options.expectedSourceRevision):
            raise QueryConflict('precondition_propagation_conflict',run_id=run.run_id)
        route='unified-answer'
        with run.limit_scope(self._profile(route)):
            def capture():
                nonlocal view,source_states
                if view is None:
                    view=self.reader.capture(plan,run_context=run,read_at=read_at)
                    source_states=view.sourceStates
                    # Compare before any lexical retrieval or provider invocation.
                    if plan.expectedDataRevision is not None and (not view.business or view.business.business_version['dataRevision']!=plan.expectedDataRevision):
                        raise QueryConflict('expected_data_revision_changed',run_id=run.run_id)
                    if plan.expectedSourceRevision is not None and (not view.source or view.source.revision!=plan.expectedSourceRevision):
                        raise QueryConflict('expected_source_revision_changed',run_id=run.run_id)
                return view
            for tool in plan.tools:
                def perform(attempt=None):
                    nonlocal metric_result,evidence,reason
                    v=capture();run.budget.check()
                    if tool=='search_knowledge':
                        wiki=wiki_evidence(v,plan.query,options,self.policy,run_context=run,embedding_provider=self.embedding_provider) if 'wiki' in plan.sourceKinds else {'evidence':[],'sourceState':{}}
                        archive=archive_evidence(v,plan.query,options,self.policy,run_context=run) if 'archive' in plan.sourceKinds else {'evidence':[],'sourceState':{}}
                        for kind,result in [('wiki',wiki),('archive',archive)]:
                            if kind in plan.sourceKinds:source_states[kind]=result['sourceState']
                        capacity=min(options.topK,effective_limits(run).maxContextChunks-(1 if 'current' in plan.parts else 0))
                        selected=fuse_evidence(wiki['evidence'],archive['evidence'],top_k=max(0,capacity))
                        evidence.extend(selected)
                        for part in plan.parts:
                            if part=='definition' and not any(e['sourceKind']=='wiki' for e in selected):missing.append('definition')
                            if part=='record' and not any(e['sourceKind']=='archive' for e in selected):missing.append('record')
                    else:
                        metric_result=read_metric(v,plan.binding,limit=min(plan.binding.get('rowLimit',200),effective_limits(run).maxMetricRows),
                                                  requested_time=plan.requestedTime,policy=self.policy,include_simulated=options.includeSimulated,run_context=run)
                        if metric_result['empty'] or metric_result['reasonCode']=='unverified_today' or 'subjects_omitted' in metric_result['warnings']:missing.append('current')
                        evidence.extend(metric_result['evidence']);reason=metric_result['reasonCode'] or reason
                        if source_states.get('business',{}).get('state')!='unavailable':
                            state='ready' if not metric_result['empty'] else ('excluded' if metric_result['reasonCode'] in ('source_excluded','simulated_source_excluded') else 'empty')
                            source_states['business']={'state':state,'reasonCode':metric_result['reasonCode']}
                    return {'evidenceCount':len(evidence)}
                try:
                    if tool_reserved:perform()
                    else:run.execute('tool',tool,None,{'query':plan.query},False,perform)
                    tools.append({'tool':tool,'status':'done','arguments':{'metricKey':plan.binding['metricKey'],'dimension':plan.binding.get('dimension')} if tool=='query_metric' else {'query':plan.query}})
                except QueryError:raise
                except RuntimeFailure as exc:
                    reason=exc.category;tools.append({'tool':tool,'status':'limited','reasonCode':exc.category});missing.extend(p for p in plan.parts if p not in missing)
                    break
            if not plan.tools:missing.extend(plan.parts or ('request',))
            if view and source_states and all(s.get('state')=='unavailable' for s in source_states.values()):raise QueryUnavailable('required_sources_unavailable',run_id=run.run_id)
            required={'definition':'wiki','record':'archive','current':'business'}
            if view and not evidence and any(source_states.get(required.get(part),{}).get('state')=='unavailable' for part in missing):
                raise QueryUnavailable('required_sources_unavailable',run_id=run.run_id)
            if not plan.tools and reason is None:reason='source_excluded'
            # Enforce one global context allowance, reserving physical input
            # before knowledge quotes. Only whole support segments are retained.
            from app.query.sources import bounded_text
            from app.query.contracts import seal_evidence
            from app.rag.identity import canonical
            limits=effective_limits(run);remaining=limits.maxContextChars;kept=[];trimmed=False
            for e in sorted(evidence,key=lambda e:0 if e['sourceKind']=='business' else 1):
                if len(kept)>=limits.maxContextChunks:trimmed=True;continue
                if e['sourceKind']=='business':
                    size=len(canonical(e['data']))
                    if size>remaining:trimmed=True;continue
                    remaining-=size;kept.append(e)
                else:
                    quote=bounded_text(e['data']['text'],remaining)
                    if quote!=e['data']['text']:trimmed=True
                    if not quote:continue
                    remaining-=len(quote);kept.append(seal_evidence({**e,'data':{**e['data'],'text':quote}}))
            if trimmed:missing.extend(p for p in plan.parts if p not in missing);reason=reason or 'context_limit'
            evidence=kept
            # Source diagnostics must not retain unbounded per-document maps.
            for state in source_states.values():state.pop('blockedReasons',None)
            result={'evidence':evidence,'sourceStates':[{'sourceKind':k,**v} for k,v in source_states.items()],'missingParts':list(dict.fromkeys(missing)),
                    'toolExecutions':tools,'readAt':view.readAt if view else None,'businessVersion':view.business.business_version if view and view.business else None,
                    'sourceRevision':view.source.revision if view and view.source else None,'indexBatchId':(view.indexState or {}).get('head') if view else None,
                    'reasonCode':reason,'metricResult':metric_result}
            return result

def default_service(repository=None):
    from app import db
    from app.query.read_view import QueryReadViewReader
    from app.rag.source import KnowledgeSource
    from app.rag.ontology import Ontology
    from app.rag.embeddings import resolve_embedding_provider
    from app.repository import Repository
    policy=ReadPolicy()
    return QueryService(QueryReadViewReader(db.get_engine(),KnowledgeSource(),policy),policy=policy,ontology=Ontology.load(),
                        embedding_provider=resolve_embedding_provider(),run_repository=repository or Repository())
