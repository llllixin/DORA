"""Pure Wiki metadata selection and stable pagination identities."""
from dataclasses import dataclass
from datetime import date
from app.rag.contracts import DOCUMENT_TYPES
from app.rag.identity import canonical, digest, document_key, source_version_hash
from app.rag.lifecycle import merge_removal_barriers, select_versions
from app.wiki.eligibility import origin_matches


class CatalogError(RuntimeError):
    def __init__(self, code, status_code=503):
        self.code, self.status_code = code, status_code
        super().__init__(code)


@dataclass(frozen=True)
class CatalogOptions:
    q: str = ''
    knowledge_type: str | None = None
    offset: int = 0
    page_size: int = 20
    include_simulated: bool = False
    expected_revision: str | None = None

    def __post_init__(self):
        if (not isinstance(self.q,str) or len(self.q)>300 or
            self.knowledge_type is not None and self.knowledge_type not in DOCUMENT_TYPES or
            type(self.offset) is not int or self.offset<0 or
            type(self.page_size) is not int or not 1<=self.page_size<=25 or
            type(self.include_simulated) is not bool or
            self.offset>0 and not self.expected_revision):
            raise CatalogError('invalid_catalog_options',422)


@dataclass(frozen=True)
class CatalogSnapshot:
    source: object
    business_date: date
    manifest: dict
    stored_hashes: dict
    origins: dict
    projection_headers: dict
    index_head: str | None
    batch: dict | None = None
    desired_profile_hash: str | None = None


def build_catalog(snapshot, options):
    documents=snapshot.source.documents
    try:
        barriers=merge_removal_barriers(snapshot.manifest,documents,mode='full')
        if any(not isinstance(key,str) or type(value) is not int or value<0 for key,value in barriers.items()):
            raise CatalogError('catalog_lifecycle_unavailable')
        selected=select_versions(documents,on_date=snapshot.business_date,barriers=barriers)
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        raise CatalogError('catalog_lifecycle_unavailable') from exc
    current=[doc for doc in selected['eligible'] if origin_matches(doc,snapshot.origins)]
    identity={'sourceRevision':snapshot.source.revision,'businessDate':snapshot.business_date.isoformat(),
              'barriers':barriers,'origins':snapshot.origins,
              'current':[(document_key(d),source_version_hash(d)) for d in current],
              'context':{'q':options.q.casefold(),'knowledgeType':options.knowledge_type,
                         'includeSimulated':options.include_simulated,'pageSize':options.page_size}}
    revision='catalog-v1:'+digest(canonical(identity))
    if options.expected_revision and options.expected_revision!=revision:
        raise CatalogError('catalog_revision_changed',409)
    query=options.q.casefold(); matching=[];pending=0
    for doc in current:
        governance=doc.get('governance') or {}
        level=governance.get('evidence_level') or 'legacy_unknown'
        simulated=doc['source_type']=='simulated' or level=='simulated'
        if simulated and not options.include_simulated:continue
        if options.knowledge_type and doc['knowledge_type']!=options.knowledge_type:continue
        if query and not any(query in value.casefold() for value in [doc['title'],doc['id'],*doc.get('concept_ids',[])]):continue
        projection_id=snapshot.manifest.get('projections',{}).get(document_key(doc))
        projection=snapshot.projection_headers.get(projection_id)
        if (not projection or projection['document_pk']!=document_key(doc) or
            projection['source_version_hash']!=source_version_hash(doc) or
            projection['profile_hash']!=snapshot.desired_profile_hash):pending+=1
        matching.append({'id':doc['id'],'title':doc['title'],'version':doc['version'],
                         'knowledgeType':doc['knowledge_type'],'sourceType':doc['source_type'],
                         'evidenceLevel':'simulated' if simulated else level,
                         'approvalStatus':'reviewed','currentEligibility':'eligible'})
    matching.sort(key=lambda row:(row['title'],row['id'],row['version']))
    batch=snapshot.batch
    status=('pending' if not batch or pending or batch['profile_hash']!=snapshot.desired_profile_hash else
            'in_sync' if batch['source_revision']==snapshot.source.revision else 'ready')
    total=len(matching)
    return {'ok':True,'cards':matching[options.offset:options.offset+options.page_size],
            'total':total,'offset':options.offset,'pageSize':options.page_size,
            'hasMore':options.offset+options.page_size<total,'sourceRevision':snapshot.source.revision,
            'catalogRevision':revision,'indexStatus':status}
