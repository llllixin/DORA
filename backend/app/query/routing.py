"""Deterministic routing using the published ontology, never a model planner."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
from datetime import date
import re
from app.query.contracts import QueryOptions,ReadPolicy,QueryInvalid

@dataclass(frozen=True)
class QueryPlan:
    query:str
    route:str
    parts:tuple=()
    tools:tuple=()
    binding:dict|None=None
    requestedTime:str='latest'
    sourceKinds:tuple=()
    reasonCode:str|None=None
    clarifications:tuple=()
    businessDate:date|None=None
    expectedDataRevision:str|None=None
    expectedSourceRevision:str|None=None

def classify_query(question,ontology,*,on_date,options=None,policy=None):
    options=options or QueryOptions();policy=policy or ReadPolicy();text=question.strip()
    unsupported=r'去年|前年|明年|往年|预测|未来|历史|过去|上(?:个)?(?:季度|月|周|星期)|下(?:个)?(?:季度|月|周|星期)|本月初|本月|本周|今年|本季度|这(?:个)?(?:周|月|季度|年)|昨天|昨日|前天|明天|明日|(?:最近|近)\s*\d+\s*[天周月年]|\d{4}(?:年|[-/])|\d{1,2}月(?:份)?|\d{1,2}/\d{1,2}|(?<![A-Za-z0-9])[Ww]\d+|(?<![A-Za-z0-9])[Qq][1-4]|[一二三四1234]季度|第[一二三四五六七八九十百\d]+(?:天|周|月|季度|年)'
    time='unsupported' if re.search(unsupported,text) else ('today' if '今天' in text or '今日' in text else 'latest')
    semantic=ontology.resolve(text,purpose='metric')
    def make(route,parts=(),tools=(),binding=None,reason=None,clarifications=()):
        kinds=tuple(k for k in options.sourceKinds if k in policy.allowedSourceKinds) if any(p in parts for p in ('definition','record')) else ()
        if route=='archive':kinds=tuple(k for k in kinds if k=='archive')
        if 'current' in parts and 'business' in policy.allowedSourceKinds:kinds+=('business',)
        if not any(k in kinds for k in ('wiki','archive')):tools=tuple(t for t in tools if t!='search_knowledge')
        if 'business' not in kinds:tools=tuple(t for t in tools if t!='query_metric')
        if options.expectedDataRevision is not None and 'current' not in parts:raise QueryInvalid('irrelevant_data_precondition')
        if options.expectedSourceRevision is not None and ('search_knowledge' not in tools or 'wiki' not in kinds):raise QueryInvalid('irrelevant_source_precondition')
        return QueryPlan(text,route,parts,tools,deepcopy(binding),time,kinds,reason,tuple(clarifications),on_date,
                         options.expectedDataRevision,options.expectedSourceRevision)
    if re.search(r'清空|删除|执行SQL|其他组织|跨租户|DROP\s|UPDATE\s',text,re.I):return make('policy',reason='readonly_policy')
    if semantic['semanticStatus']=='clarification_required':
        return make('clarify',reason=semantic['ambiguities'][0]['reasonCode'],clarifications=[a['question'] for a in semantic['ambiguities']])
    concepts=[ontology.concepts[c] for c in semantic['conceptIds']]
    if not concepts:return make('clarify',reason='unknown_concept',clarifications=('请明确已注册指标和范围。',))
    record=bool(re.search(r'记录|处理过|案例|归档',text))
    definition=bool(re.search(r'是什么|定义|口径|含义|如何|怎么|规则|流程',text))
    current=bool(re.search(r'多少|最新|当前|今天|今日|去年|预测|有哪些|现在|分别',text)) and not (record and not re.search(r'当前|最新|今天|今日',text))
    if not record and not definition:current=True
    parts=tuple(p for p,enabled in [('definition',definition),('record',record),('current',current)] if enabled)
    if 'current' in parts and (not semantic['metricBinding'] or any(c['type']=='Collection' for c in concepts)):
        return make('current',parts,reason='tool_unavailable')
    route='composite' if len(parts)>1 else ('current' if current else ('archive' if record else 'knowledge'))
    tools=tuple(t for t,enabled in [('search_knowledge',definition or record),('query_metric',current)] if enabled)
    return make(route,parts,tools,semantic['metricBinding'])

def search_plan(request,*,policy=None,on_date):
    policy=policy or ReadPolicy();o=request.options()
    kinds=tuple(k for k in o.sourceKinds if k in policy.allowedSourceKinds)
    return QueryPlan(request.query,'archive' if kinds==('archive',) else 'knowledge',('search',),
                     ('search_knowledge',) if kinds else (),sourceKinds=kinds,businessDate=on_date)
