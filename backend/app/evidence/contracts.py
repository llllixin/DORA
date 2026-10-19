"""Finite historical fact contracts, independent of current models and data reads."""
from copy import deepcopy
import json
from app.business_version import canonical_hash, loaded_code_hash
from app.series_order import period_key

FACT_FIELDS=('scopeId','sourceEpoch','generation','dataRevision','ruleVersion','ontologyVersion','sourceSetHash')
MAX_SNAPSHOT_BYTES=2097152


class EvidenceError(Exception):
    def __init__(self,code,status_code=503):
        super().__init__(code);self.code=code;self.status_code=status_code


def fact_version(version):
    if any(version.get(k) is None for k in FACT_FIELDS):raise EvidenceError('snapshot_integrity_error',409)
    return {k:deepcopy(version[k]) for k in FACT_FIELDS}


def payload_size(payload):
    try:size=len(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))
    except (TypeError,ValueError,OverflowError) as exc:raise EvidenceError('snapshot_integrity_error',409) from exc
    if size>MAX_SNAPSHOT_BYTES:raise EvidenceError('snapshot_too_large',413)
    return size


def source_grade(rows, clusters, rules, event, manifest):
    """Missing provenance belongs to each actual input, never to the upload batch."""
    required={'metric:'+row['metric_key'] for row in rows}
    if clusters:required.add('cluster')
    if rules:required.add('rules')
    if event:required.add('event')
    modes=[]
    for name in required:
        mode=manifest.get(name,'legacy_unknown')
        modes.append(mode.get('mode','legacy_unknown') if isinstance(mode,dict) else mode)
    simulated=any(mode in ('sample','simulated','demo') for mode in modes)
    return ('simulated' if simulated else ('reported' if modes and all(mode=='uploaded' for mode in modes) else 'legacy_unknown')),simulated


def build_snapshot(frozen):
    from app.engine.engine import run_engine,evidence_from_result,RULE_DEFAULTS
    raw=frozen.export_inputs();version=fact_version(frozen.business_version)
    raw['rows'].sort(key=lambda r:(r['metric_key'],period_key(r['label']),r['label'],r['dimension']))
    raw['clusters'].sort(key=lambda r:(r['store'],r['region']))
    raw['ruleRows'].sort(key=lambda r:r['key'])
    # Validate finite raw values before any rule arithmetic or coercion.
    payload_size(raw)
    result=run_engine(frozen,use_cache=False)
    insights=[{k:deepcopy(v) for k,v in i.items() if k not in ('semantics','businessVersion','reasonSource','generatedAt')} for i in result['insights']]
    evidence=[]
    for i in insights:
        e=evidence_from_result(i['id'],frozen,result);e.pop('businessVersion',None);evidence.append(e)
    level,simulated=source_grade(raw['rows'],raw['clusters'],raw['ruleRows'],raw['event'],raw['sourceManifest'])
    payload=dict(contractVersion='evidence-snapshot-v1',factVersion=version,sourceLevel=level,
                 rawSeries=raw['rows'],rawClusters=raw['clusters'],updateEvent=raw['event'],
                 rawRules=raw['ruleRows'],sourceManifest=raw['sourceManifest'],hasSimulatedInputs=simulated,
                 effectiveRules={**RULE_DEFAULTS,**raw['rules']},
                 loadedImplementation={m:loaded_code_hash(m) for m in ('app.engine.engine','app.series_order','app.business_version')},
                 signals=deepcopy(result['signals']),factInsights=insights,charts=[i.get('chart') for i in insights],storedEvidence=evidence,
                 rowLocators=[dict(index=n,rowHash=canonical_hash(r),originalEnterpriseFile=None,originalLine=None) for n,r in enumerate(raw['rows'])],
                 unknowns=['business_year_unverified','original_import_file_not_retained','no_independent_enterprise_effect_verification'])
    payload_size(payload);sha=canonical_hash(payload)
    return dict(snapshotId='snap-v1:'+sha,schemaVersion=1,scopeId=version['scopeId'],factVersion=version,
                payload=payload,payloadHash=sha,sourceLevel=level)


def validate_stored_snapshot(stored,*,scope_id):
    if stored.get('scopeId')!=scope_id:raise EvidenceError('not_found',404)
    try:
        p=stored['payload'];payload_size(p);sha=canonical_hash(p)
        level,simulated=source_grade(p['rawSeries'],p['rawClusters'],p['rawRules'],p['updateEvent'],p['sourceManifest'])
        if (stored['snapshotId']!='snap-v1:'+sha or stored['payloadHash']!=sha or stored['schemaVersion']!=1 or
            stored['factVersion']!=fact_version(p['factVersion']) or p['factVersion']['scopeId']!=scope_id or
            stored['sourceLevel']!=p['sourceLevel'] or p['sourceLevel']!=level or
            p['hasSimulatedInputs'] is not simulated):raise ValueError('identity or provenance')
    except (ValueError,KeyError,TypeError,EvidenceError) as exc:raise EvidenceError('snapshot_integrity_error',409) from exc
    return deepcopy(stored)
