"""Exact field-backed claims and deterministic rendering, with whole-packet bounds."""
from __future__ import annotations
from copy import deepcopy
import json
import re
from app.query.contracts import validate_evidence,resolve_field,effective_limits
from app.runtime.contracts import RuntimeFailure

LIMITATIONS={
 'unverified_today':'现有数据不能证明今天的测量值，以下仅引用最新已载入周期。',
 'unsupported_time_range':'现有只读工具不支持该时间范围。',
 'tool_unavailable':'该对象尚无可用的只读工具。',
 'readonly_policy':'仅支持当前服务范围内的只读查询。',
 'simulated_source_excluded':'模拟来源默认排除，当前没有符合来源策略的数据。',
 'budget_exceeded':'本次查询已达到额度上限。',
 'deadline_exceeded':'本次查询已达到时间上限。',
 'context_limit':'材料超过本次查询的上下文上限。',
 'response_too_large':'部分材料超过响应上限，未纳入答案。',
 'ambiguous_source_rows':'同一主体和周期存在冲突值，请先核对输入。',
 'incomparable_periods':'周期标签无法比较，请明确周期。',
 'unknown_concept':'请明确已注册的指标和范围。',
 'unknown_metric':'未找到该指标。',
 'source_excluded':'所需来源未获允许。',
 'empty_metric':'没有符合范围的指标输入。',
 'missing_evidence':'现有材料不足以回答此部分。',
}
def limitation_text(reason):return LIMITATIONS.get(reason,LIMITATIONS['missing_evidence'])

def _text(kind,e,row=None):
    prefix='【模拟】' if e.get('evidenceLevel')=='simulated' or e.get('sourceType')=='simulated' else ''
    if e.get('evidenceLevel')=='legacy_unknown':prefix+='【来源未核验】'
    if kind=='current_value':
        return prefix+f"最新已载入周期 {row['label']}，{row['dimension']} {e['data']['metricKey']}为 {row['value']}{row['unit']}。"+('（原输入未提供单位）' if not row['unit'] else '')
    if kind=='record_quote':return prefix+'处理记录记载：'+e['data']['text']
    return prefix+'资料记载：'+e['data']['text']

def build_claims(plan,execution,*,run_id):
    claims=[]
    def append(kind,text,e=None,paths=(),reason=None):
        claims.append({'claimId':'cl-'+str(len(claims)+1),'kind':kind,'text':text,'evidenceIds':[e['evidenceId']] if e else [],
                       'fieldPaths':[{'evidenceId':e['evidenceId'],'path':p} for p in paths] if e else [],**({'reasonCode':reason} if reason else {})})
    for e in execution['evidence']:
        if e['sourceKind']=='business':
            latest={r['dimension']:i for i,r in enumerate(e['data']['rows'])}
            for index in latest.values():
                row=e['data']['rows'][index]
                append('current_value',_text('current_value',e,row),e,[f'data.rows[{index}].{k}' for k in ('value','label','dimension','unit')])
        else:
            kind='record_quote' if e['sourceKind']=='archive' or e.get('knowledgeType')=='case' else 'definition_quote'
            append(kind,_text(kind,e),e,['data.text'])
    if execution.get('missingParts') or not claims:
        reason=execution.get('reasonCode') or plan.reasonCode or 'missing_evidence'
        append('limitation',limitation_text(reason),reason=reason)
    return claims

def validate_claims(claims,evidence,*,plan):
    by_id={}
    for e in evidence:
        validate_evidence(e)
        if e['evidenceId'] in by_id and by_id[e['evidenceId']]!=e:raise ValueError('duplicate evidence identity')
        by_id[e['evidenceId']]=e
    ids=set()
    for claim in claims:
        if claim['claimId'] in ids:raise ValueError('duplicate claim')
        ids.add(claim['claimId']);kind=claim['kind']
        if kind=='limitation':
            if claim['evidenceIds'] or claim['fieldPaths'] or claim['text']!=limitation_text(claim.get('reasonCode')):raise ValueError('invalid limitation')
            continue
        if kind not in ('current_value','definition_quote','record_quote') or len(claim['evidenceIds'])!=1:raise ValueError('unsupported claim kind')
        identity=claim['evidenceIds'][0]
        if identity not in by_id:raise ValueError('unknown evidence')
        e=by_id[identity];refs=claim['fieldPaths']
        if not refs or any(r['evidenceId']!=identity for r in refs):raise ValueError('wrong evidence reference')
        for ref in refs:resolve_field(e,ref['path'])
        if kind=='current_value':
            if e['sourceKind']!='business' or not plan.binding:raise ValueError('current value requires physical input')
            matches=[re.fullmatch(r'data\.rows\[([0-9]{1,3})\]\.(value|label|dimension|unit)',r['path']) for r in refs]
            if len(matches)!=4 or any(m is None for m in matches) or len({m[1] for m in matches})!=1 or {m[2] for m in matches}!={'value','label','dimension','unit'}:raise ValueError('incomplete row references')
            index=int(matches[0][1]);row=e['data']['rows'][index]
            if (e['data']['metricKey']!=plan.binding['metricKey'] or e['subject']['metricKey']!=plan.binding['metricKey'] or
                (plan.binding.get('dimension') is not None and row['dimension']!=plan.binding['dimension']) or
                (e['subject'].get('dimension') is not None and row['dimension']!=e['subject']['dimension'])):raise ValueError('wrong subject')
            # A quote of an older row cannot be relabelled as the latest row.
            if any(r['dimension']==row['dimension'] for r in e['data']['rows'][index+1:]):raise ValueError('not latest row')
            expected=_text(kind,e,row)
        else:
            if e['sourceKind'] not in ('wiki','archive') or [r['path'] for r in refs]!=['data.text']:raise ValueError('quote requires source text')
            if kind=='definition_quote' and (e['sourceKind']!='wiki' or e.get('knowledgeType')=='case'):raise ValueError('record is not definition')
            if kind=='record_quote' and e['sourceKind']=='wiki' and e.get('knowledgeType')!='case':raise ValueError('invalid record')
            expected=_text(kind,e)
        if claim['text']!=expected:raise ValueError('changed claim text')

def render_answer(claims):return '\n'.join(c['text'] for c in claims)

def pack_response(payload,*,run_context):
    value=deepcopy(payload);cap=effective_limits(run_context).maxResultBytes
    value.pop('metricResult',None);value.pop('diagnostic',None)
    def size():return len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))
    while size()>cap-1024 and value.get('evidence'):
        # Drop whole evidence/claims; never truncate a number, sentence or unit.
        candidates=[i for i,e in enumerate(value['evidence']) if e['sourceKind']!='business']
        index=candidates[-1] if candidates else len(value['evidence'])-1
        removed=value['evidence'].pop(index)['evidenceId']
        value['claims']=[c for c in value.get('claims',[]) if removed not in c['evidenceIds']]
        for key in ('citations','hits','references'):
            if key in value:value[key]=[e for e in value[key] if e.get('evidenceId')!=removed]
        if 'answer' in value:value['answer']=render_answer(value['claims'])
        value['missingParts']=list(dict.fromkeys([*value.get('missingParts',[]),'response_limit']))
        value.update(ok=False,status='partial' if value['evidence'] else 'limited',reasonCode='response_too_large')
    if size()>cap-1024:raise RuntimeFailure('response_too_large')
    return value
