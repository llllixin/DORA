"""Read only sources a fixed graph batch actually uses; build caps do not block history."""
from copy import deepcopy
import json
from sqlalchemy import select,func,or_
from app import models as m
from app.business_version import SCOPE_ID,canonical_hash
from app.graph.contracts import GraphError
from app.graph.source import row_data,source_inventory,byte_size,validate_binding
from app.evidence.repository import snapshot_view
from app.evidence.contracts import validate_stored_snapshot,EvidenceError
from app.rag.contracts import KNOWLEDGE_ROOT
from app.rag.identity import document_key,source_version_hash
from app.rag.lifecycle import select_versions,merge_removal_barriers
from app.rag.ontology_contracts import validate_ontology,content_hash
from app.wiki.candidates import available


class LazyRecords(dict):
    def __init__(self,load):super().__init__();self.load=load
    def __missing__(self,key):
        value=self.load(key);self[key]=value;return value
    def get(self,key,default=None):
        try:return self[key]
        except KeyError:return default


def batch_sources(reader,session,source,expected,budget):
    budget.check();vector=deepcopy(expected);metadata={r['key']:r for r in expected['records']}
    vector.update(sourceRevision=source.revision,effectiveDate=source.business_date.isoformat(),
                  inventory=source_inventory(session,budget))
    # Only metadata for sources of this immutable batch is enumerated here.
    binding_ids=[k[len('binding:'):] for k in metadata if k.startswith('binding:')]
    budget.prepare(session)
    hints=session.execute(select(m.EvidenceBinding.binding_id,m.EvidenceBinding.source_kind,m.EvidenceBinding.source_instance_id)
        .where(m.EvidenceBinding.scope_id==SCOPE_ID,m.EvidenceBinding.binding_id.in_(binding_ids))).all() if binding_ids else []
    pairs={(r.source_kind,r.source_instance_id) for r in hints}
    instances={p[1] for p in pairs}
    budget.prepare(session)
    removed={(r.source_kind,r.source_instance_id) for r in session.scalars(select(m.EvidenceSourceEvent).where(
        m.EvidenceSourceEvent.scope_id==SCOPE_ID,m.EvidenceSourceEvent.source_instance_id.in_(instances),
        m.EvidenceSourceEvent.event_type=='deleted'))} if instances else set()
    live=set()
    for model,kind in [(m.ActionCase,'action_case'),(m.WatchTarget,'watch_target')]:
        budget.prepare(session)
        if instances:live|={(kind,i) for i in session.scalars(select(model.history_instance_id).where(model.history_instance_id.in_(instances)))}
    statuses={'binding:'+r.binding_id:('deleted' if (r.source_kind,r.source_instance_id) in removed else
              'available' if (r.source_kind,r.source_instance_id) in live else 'unavailable') for r in hints}
    documents=source.documents
    state=session.get(m.RagIndexState,'repository-json')
    previous=session.get(m.RagIndexBatch,state.head_batch_id) if state and state.head_batch_id else None
    manifest=previous.manifest_json if previous else {'barriers':expected['barriers'],'versions':{}}
    barriers=merge_removal_barriers(manifest,documents,mode='full')
    selection=select_versions(documents,on_date=source.business_date,barriers=barriers)
    eligible={document_key(d):d for d in selection['eligible']};formal={document_key(d):d for d in documents}
    vector['barriers']=barriers
    for key,entry in metadata.items():
        budget.check()
        if key.startswith('document:'):
            pk=key[len('document:'):];doc=eligible.get(pk)
            status='available' if doc and canonical_hash(doc)==entry['hash'] else 'changed'
            if pk not in formal:status='removed'
            identity=pk.rsplit('@',1)[0]
            if identity in selection['reasons']:status=selection['reasons'][identity]
            if doc:
                origin=(doc.get('governance') or {}).get('origin') or {}
                if origin:
                    budget.prepare(session);candidate=session.get(m.KnowledgeCandidate,origin.get('candidate_id'))
                    if not (candidate and available(session,candidate) and candidate.revision==origin.get('revision')
                            and candidate.source_payload_hash==origin.get('source_hash')):status='origin_unavailable'
            statuses[key]=status
    vector['records']=[{**r,'status':statuses.get(r['key'],r['status'])} for r in expected['records']]
    used_bytes=0
    def record(kind,native,data,version,level):
        nonlocal used_bytes
        budget.check();used_bytes+=byte_size(data)
        if used_bytes>reader.limits.maxSourceBytes:raise GraphError('read_view_limit')
        key=kind+':'+native
        value=dict(kind=kind,sourceId=native,version=version,data=deepcopy(data),hash=canonical_hash(data),
                   level=level,status=statuses.get(key,'available'))
        budget.check();return value
    def load(key):
        if key not in metadata:raise KeyError(key)
        budget.prepare(session);kind,native=key.split(':',1)
        try:
            if kind=='snapshot':
                row=session.get(m.EvidenceSnapshot,native)
                if row is None or row.scope_id!=SCOPE_ID:raise GraphError('source_integrity_error')
                value=validate_stored_snapshot(snapshot_view(row),scope_id=SCOPE_ID)
                for insight in value['payload']['factInsights']:
                    occurrence=session.get(m.InsightOccurrence,insight['occurrenceId'])
                    if (not occurrence or occurrence.scope_id!=SCOPE_ID or occurrence.judgment!=insight
                        or occurrence.fact_identity!=value['factVersion']
                        or occurrence.content_hash!=canonical_hash([occurrence.fact_identity,occurrence.judgment])):
                        raise GraphError('source_integrity_error')
                return record(kind,native,value,value['payloadHash'],value['sourceLevel'])
            if kind=='binding':
                row=session.get(m.EvidenceBinding,native)
                if row is None or row.scope_id!=SCOPE_ID:raise GraphError('source_integrity_error')
                data=row_data(row)
                snap=records['snapshot:'+row.snapshot_id]['data'] if row.snapshot_id else None
                validate_binding(data,snap,session)
                return record(kind,native,data,native,snap['sourceLevel'] if snap else 'legacy_unknown')
            if kind=='document':
                row=session.get(m.RagDocument,native)
                if row is None or row.source_snapshot is None:raise GraphError('source_integrity_error')
                data=row.source_snapshot
                if document_key(data)!=native or row.source_version_hash!=source_version_hash(data):raise GraphError('source_integrity_error')
                level=(data.get('governance') or {}).get('evidence_level') or 'legacy_unknown'
                if data.get('source_type')=='simulated':level='simulated'
                return record(kind,native,data,row.source_version_hash,level)
            if kind=='ontology':
                rid,_,sha=native.partition(':');directory=KNOWLEDGE_ROOT/'ontology/releases'
                release=json.loads((directory/'manifest.json').read_text())[rid];path=(directory/release['file']).resolve()
                if not path.is_relative_to(directory.resolve()) or release['status']!='reviewed':raise GraphError('source_integrity_error')
                data=json.loads(path.read_text());validate_ontology(data)
                if content_hash(data)!=release['contentHash'] or (sha and sha!=release['contentHash']):raise GraphError('source_integrity_error')
                return record(kind,native,data,release['contentHash'],'project')
            if kind=='rule':
                rule=expected['rules'][native]
                predicate=(m.EvidenceSnapshot.scope_id==SCOPE_ID,
                    m.EvidenceSnapshot.fact_version['ruleVersion'].as_string()==rule['ruleVersion'],
                    m.EvidenceSnapshot.fact_version['ontologyVersion'].as_string()==rule['ontologyVersion'])
                row=session.scalar(select(m.EvidenceSnapshot).where(*predicate).order_by(m.EvidenceSnapshot.snapshot_id).limit(1))
                if row is None:raise GraphError('source_integrity_error')
                snap=validate_stored_snapshot(snapshot_view(row),scope_id=SCOPE_ID)
                data={**rule,'effectiveRules':snap['payload']['effectiveRules']}
                levels=set(session.scalars(select(m.EvidenceSnapshot.source_level).where(*predicate).distinct()))
                level='simulated' if 'simulated' in levels else 'legacy_unknown' if 'legacy_unknown' in levels else 'reported'
                return record(kind,native,data,rule['ruleVersion'],level)
            raise GraphError('source_integrity_error')
        except GraphError:raise
        except (EvidenceError,KeyError,ValueError,TypeError,OSError) as exc:raise GraphError('source_integrity_error') from exc
    records=LazyRecords(load)
    budget.check()
    return dict(records=records,vector=vector,session=session)
