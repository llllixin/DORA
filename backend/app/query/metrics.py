"""Read original metric rows with explicit subject, period, unit and provenance."""
from __future__ import annotations
from copy import deepcopy
from datetime import date
import re
from app.series_order import period_key
from app.query.sources import SIMULATED,base_evidence
from app.query.contracts import seal_evidence

def metric_binding_for_tool(metric_key,dimension,ontology):
    bindings=[c['metricBinding'] for c in ontology.concepts.values() if c['type']=='Metric' and c.get('metricBinding') and c['metricBinding']['metricKey']==metric_key]
    if not bindings:return None
    binding=deepcopy(bindings[0]);policy=binding['dimensionPolicy']
    if dimension:
        valid=(dimension==binding.get('dimension')) if policy in ('fixed','fixed_with_east_view') else bool(re.fullmatch(r'门店\s*[0-9]+' if policy=='store_or_all_rows' else r'供应商[A-Za-z0-9]+',dimension))
        if not valid:return {**binding,'reasonCode':'unsupported_dimension','dimension':dimension}
        binding['dimension']=dimension
    return binding

def observed_period(label):
    iso=None
    if isinstance(label,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',label):
        try:iso=date.fromisoformat(label).isoformat()
        except ValueError:pass
    return {'label':label,'isoDate':iso}

def freshness(requested_time,periods,*,business_date):
    if requested_time=='unsupported':return {'freshnessStatus':'unsupported_time_range','reasonCode':'unsupported_time_range'}
    if requested_time=='today':
        verified=bool(periods) and all(p['isoDate']==business_date.isoformat() for p in periods)
        return {'freshnessStatus':'verified_today' if verified else 'unverified_today','reasonCode':None if verified else 'unverified_today'}
    return {'freshnessStatus':'latest_loaded','reasonCode':None}

def _family(label):
    if label in ('上月','本月初','当前'):return 'relative'
    if observed_period(label)['isoDate']:return 'iso'
    return re.sub(r'\d+','#',label).lower()

def select_metric_rows(rows,*,dimension,limit):
    selected=[deepcopy(r) for r in rows if dimension is None or r['dimension']==dimension];unique={}
    for r in selected:
        key=(r['dimension'],r['label'])
        if key in unique and (unique[key]['value']!=r['value'] or unique[key]['unit']!=r['unit']):raise ValueError('ambiguous_source_rows')
        unique[key]=r
    groups={}
    for r in unique.values():groups.setdefault(r['dimension'],[]).append(r)
    if len({_family(r['label']) for r in unique.values()})>1:raise ValueError('incomparable_periods')
    for group in groups.values():group.sort(key=lambda r:(period_key(r['label']),r['label']))
    # Reserve each subject's latest row before older history. Truncation remains
    # explicit in read_metric; it never becomes an aggregate or all-subject claim.
    picked=[];depth=1
    while len(picked)<limit:
        layer=[group[-depth] for _,group in sorted(groups.items()) if len(group)>=depth]
        if not layer:break
        picked.extend(layer[:limit-len(picked)]);depth+=1
    return sorted(picked,key=lambda r:(period_key(r['label']),r['label'],r['dimension']))

def read_metric(view,binding,*,limit,requested_time,policy,include_simulated,run_context):
    run_context.budget.check();key=binding['metricKey'];dimension=binding.get('dimension')
    version=view.business.business_version if view.business else None
    mode=view.business.source_mode_for(key) if view.business else 'legacy_unknown'
    reason=binding.get('reasonCode');rows=[];warnings=[];periods=[]
    if reason:pass
    elif view.business is None:reason='data_source_unavailable'
    elif 'business' not in policy.allowedSourceKinds:reason='source_excluded'
    elif mode in SIMULATED and not (include_simulated and policy.allowSimulated):reason='simulated_source_excluded'
    elif requested_time=='unsupported':reason='unsupported_time_range'
    else:
        original=view.business.get_series(key)
        try:rows=select_metric_rows(original,dimension=dimension,limit=min(limit,200))
        except ValueError as exc:reason=str(exc)
        if len({r['dimension'] for r in rows})<len({r['dimension'] for r in original if dimension is None or r['dimension']==dimension}):warnings.append('subjects_omitted')
        if any(not r['unit'] for r in rows):warnings.append('unknown_unit')
        latest={r['dimension']:r for r in rows}
        periods=[observed_period(r['label']) for r in latest.values()]
    state=freshness(requested_time,periods,business_date=view.businessDate)
    reason=reason or (state['reasonCode'] if rows else 'empty_metric')
    evidence=[]
    if rows:
        e=base_evidence(view,'business',source_type='simulated' if mode in SIMULATED else 'project',mode=mode,
                        level='simulated' if mode in SIMULATED else ('observed_input' if mode=='uploaded' else 'legacy_unknown'),approval='observed_input')
        e.update(subject={'metricKey':key,'dimension':dimension,'sourceScopeDescription':'逐主体原始输入，不作聚合' if dimension is None else dimension},
                 observedPeriod=periods[0] if len(periods)==1 else {'label':None,'isoDate':None},dataRevision=version['dataRevision'],businessVersion=version,
                 data={'metricKey':key,'rows':rows})
        evidence=[seal_evidence(e)]
    return {'metricKey':key,'dimension':dimension,'rows':rows,'count':len(rows),'empty':not rows,'businessVersion':version,
            'sourceMode':mode,'evidence':evidence,**state,'reasonCode':reason,'warnings':warnings}
