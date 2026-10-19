"""Card shape, published legacy boundary and content-bound local review."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.rag.contracts import PROJECT_ROOT, KNOWLEDGE_ROOT, RagContractError

SECTIONS = {
    'metric': ('definition','physical_binding','calculation_boundary','comparison_scope','usage','limitations'),
    'rule': ('inputs','predicate','configuration','result','handling','limitations'),
    'sop': ('preconditions','steps','result','failure_handling','limitations'),
    'case': ('context','observed_problem','handling','verification','result','reuse_scope','limitations'),
}
TYPES = {'glossary':'metric','rule':'rule','procedure':'sop','case':'case','external':'sop'}
PAYLOAD_FIELDS = ('schema_version','id','title','knowledge_type','content','metric_keys','dimensions','concept_ids','aliases','source_type','source_ref','source_url','valid_from','valid_to','wiki_card')


def require(ok, message):
    if not ok: raise RagContractError(message)


def canonical_hash(value):
    try:
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (TypeError,ValueError) as exc: raise RagContractError('invalid JSON payload') from exc
    return hashlib.sha256(raw.encode()).hexdigest()


def payload_hash(doc):
    payload={k:doc.get(k) for k in PAYLOAD_FIELDS}
    payload['governance']={k:v for k,v in doc.get('governance',{}).items() if k!='review'}
    return canonical_hash(payload)


def is_legacy(doc):
    manifest=json.loads((KNOWLEDGE_ROOT/'legacy-release-manifest.json').read_text())
    wanted=next((r['hash'] for r in manifest['records'] if r['id']==doc.get('id') and r['version']==doc.get('version')),None)
    return wanted==canonical_hash(doc)


def source_file(ref):
    require(isinstance(ref,str) and bool(ref.strip()),'source ref must be nonempty')
    path=(PROJECT_ROOT/ref).resolve()
    require(path.is_relative_to(PROJECT_ROOT) and path.is_file(),'source file missing or outside repository')
    return path


def compile_content(card):
    return '\n\n'.join(f'{key}：{value}' for key,value in card['sections'].items())


def validate_card(doc):
    require(type(doc.get('schema_version')) is int and doc['schema_version']==2,'new records require schema_version=2')
    card=doc.get('wiki_card');gov=doc.get('governance')
    require(isinstance(card,dict) and isinstance(gov,dict),'wiki_card and governance required')
    require(card.get('card_type')==TYPES.get(doc.get('knowledge_type')),'card type mismatch')
    sections=card.get('sections')
    require(isinstance(sections,dict) and set(sections)==set(SECTIONS[card['card_type']]),'missing/extra card section')
    require(all(isinstance(v,str) and bool(v.strip()) for v in sections.values()),'card sections must contain text')
    require(isinstance(card.get('concept_note'),str) and bool(card['concept_note'].strip()),'concept_note required')
    require(doc['content']==compile_content(card),'content differs from structured card')
    from app.rag.ontology import Ontology
    require(set(doc['concept_ids'])<=set(Ontology.load().concepts),'unknown ontology concept')
    level=gov.get('evidence_level')
    require(level in {'project_definition','simulated','reported'},'unsupported evidence level')
    require(doc['source_type']!='verified_case','A02 does not publish verified_case')
    require((doc['source_type']=='simulated')==(level=='simulated'),'simulated provenance must be preserved')
    require(isinstance(gov.get('applicability'),str) and bool(gov['applicability'].strip()),'applicability required')
    require(isinstance(gov.get('unknowns'),list) and all(isinstance(v,str) and bool(v.strip()) for v in gov['unknowns']),'unknowns must be text list')
    refs=gov.get('source_refs')
    require(isinstance(refs,list) and bool(refs),'source_refs required')
    if doc['source_type']=='official':
        url=doc.get('source_url')
        require(isinstance(url,str) and url.startswith('https://') and bool(urlsplit(url).hostname) and url in refs,'primary official citation must be audited HTTPS URL')
        require(not doc.get('source_ref') or doc['source_ref'] in refs,'secondary citation not audited')
    else:
        require(doc.get('source_ref') in refs,'primary citation must belong to audited sources')
    for ref in refs:
        if isinstance(ref,str) and ref.startswith('https://'):
            require(doc['source_type']=='official' and ref==doc.get('source_url') and bool(urlsplit(ref).hostname),'external source must match official URL')
        else: source_file(ref)
    if doc['status'] in {'reviewed','retired'}:
        review=gov.get('review');require(isinstance(review,dict),'content-bound review required')
        require(all(isinstance(review.get(k),str) and bool(review[k].strip()) for k in ('actor','timestamp','reason','payload_hash')),'review fields required')
        require(review['actor']==doc['reviewed_by'],'review actor mismatch')
        require(review.get('decision')==('retire' if doc['status']=='retired' else 'approve'),'review decision mismatch')
        require(type(review.get('base_version')) is int and review['base_version']>=0,'expected base version required')
        try: datetime.fromisoformat(review['timestamp'])
        except ValueError as exc: raise RagContractError('invalid review timestamp') from exc
        require(review['payload_hash']==payload_hash(doc),'review no longer matches payload')
    else:
        require(gov.get('review') is None and doc.get('reviewed_by') is None,'draft cannot claim prior approval')
    return deepcopy(doc)


def approve(doc, *, actor, reason, base_version):
    require(isinstance(actor,str) and bool(actor.strip()) and isinstance(reason,str) and bool(reason.strip()),'explicit operator and reason required')
    require(type(base_version) is int and base_version>=0,'base_version must be nonnegative integer')
    out=deepcopy(doc);out['status']='draft';out['reviewed_by']=None;out['governance']['review']=None
    from app.rag.contracts import validate_document
    validate_document(out)
    out['governance']['source_hashes']={ref:hashlib.sha256(source_file(ref).read_bytes()).hexdigest() for ref in out['governance']['source_refs'] if not ref.startswith('https://')}
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    out['status']='reviewed';out['reviewed_by']=actor.strip();out['updated_at']=now
    out['governance']['review']={'actor':actor.strip(),'reason':reason.strip(),'timestamp':now,'decision':'approve','base_version':base_version,'payload_hash':payload_hash(out)}
    return validate_document(out)


def retire(doc, *, actor, reason, base_version):
    out=approve(doc,actor=actor,reason=reason,base_version=base_version)
    out['status']='retired';out['governance']['review']['decision']='retire'
    return validate_card(out)
