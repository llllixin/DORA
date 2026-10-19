"""Pure filtering shared by live A06 and frozen A07 views; no IO."""
from app.rag.index_store import assert_immutable,validate_projection
from app.rag.lifecycle import select_versions,merge_removal_barriers
from app.rag.identity import document_key,source_version_hash,profile_hash

def build_retrieval_snapshot(source,state,*,knowledge_types=None,desired_profile=None,budget=None,document_predicate=None):
    from app.rag.repository import RagRepository
    assert_immutable(source.documents, state['versions'])
    manifest = state['manifest']
    barriers = merge_removal_barriers(manifest, source.documents, mode='full')
    selection = select_versions(source.documents, on_date=source.business_date, barriers=barriers)
    batch=state['batch']; expected=profile_hash(desired_profile) if desired_profile else (batch['profile_hash'] if batch else None)
    chunks=[];eligible_count=0;pending=0; reasons=dict(selection['reasons']);origin_blocked=0
    for doc in selection['eligible']:
        if document_predicate and not document_predicate(doc):continue
        if document_predicate and knowledge_types and doc['knowledge_type'] not in knowledge_types:continue
        eligible_count+=1
        if budget:budget.check()
        origin=(doc.get('governance') or {}).get('origin')
        if origin:
            live=state['origins'].get(origin.get('candidate_id'),{})
            if not (live.get('available') and live.get('revision')==origin.get('revision') and live.get('source_hash')==origin.get('source_hash')):
                reasons[doc['id']]='origin_unavailable';origin_blocked+=1;continue
        key=document_key(doc); pid=manifest.get('projections',{}).get(key)
        projection=state['projections'].get(pid)
        if not projection or projection['source_version_hash'] != source_version_hash(doc):
            pending+=1;continue
        validate_projection(projection)
        if expected and projection['profile_hash']!=expected:pending+=1
        if knowledge_types and doc['knowledge_type'] not in knowledge_types:continue
        for row in projection['chunks_json']:
            value=RagRepository._chunk_dict(type('Chunk',(),row)(),type('Doc',(),{'knowledge_type':doc['knowledge_type']})())
            value['embedding_profile_hash']=projection['profile_hash'];chunks.append(value)
    profile_pending=bool(batch and expected!=batch['profile_hash'])
    status=('pending' if not batch or pending or profile_pending else
            'in_sync' if batch['source_revision']==source.revision else 'ready')
    if document_predicate is not None and not eligible_count:status='ready'
    missing_topics={d['id'] for d in manifest.get('versions',{}).values()}-{d['id'] for d in source.documents}
    for identity in missing_topics:reasons[identity]='removed'
    return {'chunks':chunks,'index':{'asOf':source.as_of,'businessDate':source.business_date.isoformat(),
        'sourceRevision':source.revision,'indexBatchId':state['head'], 'embeddingProfileHash':batch['profile_hash'] if batch else None,
        'indexStatus':status,'pendingCount':pending,'blockedCount':len(reasons),'blockedReasons':reasons}}
