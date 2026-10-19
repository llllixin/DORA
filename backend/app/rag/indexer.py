"""确定性分块与幂等索引准备。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.rag.contracts import is_current_reviewed, load_documents, validate_document
from app.rag.embeddings import EmbeddingProvider, resolve_embedding_provider
from app.rag.repository import RagRepository
from app.runtime.executor import RunContext, invoke_provider, classify
from app.runtime import records


class RagIndexer:
    def __init__(self, repository: RagRepository | None = None, embedding_provider: EmbeddingProvider | None = None, run_repository=None):
        self.repository = repository or RagRepository()
        self.embedding_provider = embedding_provider or resolve_embedding_provider()
        self.run_repository = run_repository

    def rebuild(self, documents=None, *, run_context=None):
        from copy import deepcopy
        from app import db
        from app.rag.identity import document_key, source_version_hash, embedding_profile, profile_hash, canonical, digest
        from app.rag.lifecycle import select_versions, merge_removal_barriers
        from app.rag.index_store import assert_immutable, validate_projection
        from app.rag.index_lock import build_lock
        from app.rag.contracts import RagIndexConflict
        run = run_context or RunContext('rag-index', external=getattr(self.embedding_provider,'external',False) is True,
            repository=self.run_repository or records.default_repository())
        profile=embedding_profile(self.embedding_provider);ph=profile_hash(profile)
        report={'mode':'full' if documents is None else 'patch','sourceRevision':None,'embeddingProfileHash':ph,
            'previousBatchId':None,'indexBatchId':None,'projectionCreated':0,'projectionSkipped':0,
            'embeddedInputs':0,'reusedInputs':0,'draftVersions':0,'retiredVersions':0,'expiredVersions':0,
            'futureVersions':0,'removedBarriers':0,'blockedOrigins':0,'pendingVersions':0}
        try:
            with build_lock(db.get_engine(),run.budget) as connection:
                source=self.repository.source.snapshot(budget=run.budget)
                report['sourceRevision']=source.revision
                docs=source.documents if documents is None else [validate_document(d) for d in documents]
                if len({document_key(d) for d in docs})!=len(docs):raise ValueError('id + version 必须唯一')
                if documents is not None:
                    authoritative={document_key(d):d for d in source.documents}
                    for doc in docs:
                        current=authoritative.get(document_key(doc))
                        if current is None or source_version_hash(current)!=source_version_hash(doc):
                            raise RagIndexConflict('document_version_conflict')
                    # Patch selects topics; freeze their actual source versions, including
                    # the effective version whose projection is about to be activated.
                    touched={d['id'] for d in docs}
                    docs=[d for d in source.documents if d['id'] in touched]
                store=self.repository.index_store; state=store.read_snapshot(documents=source.documents)
                report['previousBatchId']=state['head']
                assert_immutable(docs,state['versions']);assert_immutable(source.documents,state['versions'])
                mode='full' if documents is None else 'patch'
                manifest=deepcopy(state['manifest']); barriers=merge_removal_barriers(manifest,source.documents,mode=mode)
                selection=select_versions(source.documents,on_date=source.business_date,barriers=barriers)
                report.update({
                    'draftVersions':sum(d['status']=='draft' for d in docs),'retiredVersions':sum(d['status']=='retired' for d in docs),
                    'expiredVersions':sum(bool(d.get('valid_to')) and d['valid_to']<source.business_date.isoformat() for d in docs),
                    'futureVersions':sum(d['valid_from']>source.business_date.isoformat() for d in docs),
                    'removedBarriers':len(barriers)})
                reusable={}
                for p in state['projections'].values():
                    if p['profile_hash']==ph:
                        validate_projection(p)
                        for c in p['chunks_json']:
                            self._validate_vectors([c['embedding']],1);reusable[c['embedding_input_hash']]=c['embedding']
                touched={d['id'] for d in docs};prepared=[];mapping=dict(manifest.get('projections',{}))
                for doc in selection['eligible']:
                    if mode=='patch' and doc['id'] not in touched:continue
                    origin=(doc.get('governance') or {}).get('origin')
                    if origin:
                        live=state['origins'].get(origin.get('candidate_id'),{})
                        if not (live.get('available') and live.get('revision')==origin.get('revision') and live.get('source_hash')==origin.get('source_hash')):
                            report['blockedOrigins']+=1;continue
                    key=document_key(doc);pid='p-'+digest(canonical([key,ph]))
                    if pid in state['projections']:
                        if state['projections'][pid]['source_version_hash']!=source_version_hash(doc):raise RagIndexConflict('document_version_conflict')
                        mapping[key]=pid;report['projectionSkipped']+=1;continue
                    texts=[f"{doc['title']}\n{c}" for c in split_text(doc['content'])]
                    missing=list(dict.fromkeys(t for t in texts if digest(t) not in reusable))
                    report['reusedInputs']+=len(texts)-len(missing);response_model=None
                    while missing:
                        group=[]
                        while missing and len(json.dumps({'input':group+[missing[0]]},ensure_ascii=False).encode())<=run.profile.maxRequestBytes:group.append(missing.pop(0))
                        if not group:
                            from app.runtime.contracts import RuntimeFailure
                            raise RuntimeFailure('context_limit')
                        start=len(run.events);vectors=invoke_provider(self.embedding_provider,'embed',(group,),run,'index_embedding')
                        self._validate_vectors(vectors,len(group))
                        attempts=[e for e in run.events[start:] if e.get('type')=='model_attempt' and e.get('status')=='done']
                        response_model=attempts[-1].get('responseModel') if attempts else None
                        if response_model is not None and response_model!=self.embedding_provider.model:
                            from app.runtime.contracts import RuntimeFailure
                            raise RuntimeFailure('embedding_profile_mismatch')
                        reusable.update({digest(t):v for t,v in zip(group,vectors)});report['embeddedInputs']+=len(group)
                    item=self._prepare(doc,run_context=run,_vectors=[reusable[digest(t)] for t in texts])
                    for c,t in zip(item['chunks'],texts):c['embedding_input_hash']=digest(t)
                    prepared.append({'projection_id':pid,'document_pk':key,'source_version_hash':source_version_hash(doc),
                        'profile_hash':ph,'profile_json':{**profile,'responseModel':response_model},'chunks_json':item['chunks']})
                    mapping[key]=pid;report['projectionCreated']+=1
                versions=dict(manifest.get('versions',{}))
                for doc in docs:versions[document_key(doc)]={k:doc.get(k) for k in ('id','version','status','valid_from','valid_to')}
                new_manifest={'versions':versions,'projections':mapping,'barriers':barriers}
                available={**state['projections'],**{p['projection_id']:p for p in prepared}}
                for doc in selection['eligible']:
                    origin=(doc.get('governance') or {}).get('origin')
                    if origin:
                        live=state['origins'].get(origin.get('candidate_id'),{})
                        if not (live.get('available') and live.get('revision')==origin.get('revision') and live.get('source_hash')==origin.get('source_hash')):continue
                    projection=available.get(mapping.get(document_key(doc)))
                    if not projection or projection['profile_hash']!=ph or projection['source_version_hash']!=source_version_hash(doc):
                        report['pendingVersions']+=1
                run.budget.check()
                with self.repository.source.locked_snapshot(budget=run.budget) as current:
                    if current.revision!=source.revision:raise RagIndexConflict('source_changed')
                    result=store.commit_batch(docs,prepared,new_manifest,report,expected_head=state['head'],commit_guard=run.budget.check,connection=connection)
                result.update(documents=self.repository.count('documents'),chunks=self.repository.count('chunks'))
            return run.finish({'ok':True,'provider':self.embedding_provider.kind,'model':self.embedding_provider.model,**result})
        except Exception as exc:
            from sqlalchemy.exc import SQLAlchemyError
            if isinstance(exc,SQLAlchemyError):
                from app.rag.contracts import RagIndexUnavailable
                failure_exc=RagIndexUnavailable('data_source_unavailable')
                failure_exc.__cause__=exc;exc=failure_exc
            failure=classify(exc);reason=getattr(exc,'code',failure.category)
            run.finish({'ok':False,'reason':reason,'indexReport':report},'limited' if failure.category in ('budget_exceeded','deadline_exceeded','external_disabled') else 'failed')
            exc.run_id=run.run_id
            raise exc

    def _validate_vectors(self, vectors, count):
        import math
        from app.runtime.contracts import RuntimeFailure
        if not isinstance(vectors,list) or len(vectors)!=count or not all(isinstance(v,list) and len(v)==self.embedding_provider.dimensions and all(type(x) in (int,float) and math.isfinite(x) for x in v) for v in vectors):
            raise RuntimeFailure('invalid_vector')

    def _prepare(self, doc: dict[str, Any], *, run_context=None, _vectors=None) -> dict[str, Any]:
        chunks = split_text(doc["content"])
        texts = [f"{doc['title']}\n{chunk}" for chunk in chunks]
        vectors = _vectors if _vectors is not None else (invoke_provider(self.embedding_provider, 'embed', (texts,), run_context, 'index_embedding') if run_context else self.embedding_provider.embed(texts))
        self._validate_vectors(vectors, len(texts))
        pk = f"{doc['id']}@{doc['version']}"
        metadata = {
            "metric_keys": doc.get("metric_keys", []), "dimensions": doc.get("dimensions", []),
            "concept_ids": doc.get("concept_ids", []), "aliases": doc.get("aliases", []),
            "source_type": doc["source_type"], "source_ref": doc.get("source_ref", ""),
            "source_url": doc.get("source_url", ""), "valid_from": doc["valid_from"],
            "valid_to": doc.get("valid_to"), "reviewed_by": doc["reviewed_by"],
            "updated_at": doc["updated_at"], "is_current": is_current_reviewed(doc),
            "schema_version": doc.get("schema_version", 1),
            "wiki_card": doc.get("wiki_card"), "governance": doc.get("governance"),
        }
        chunk_rows = []
        for index, (content, vector) in enumerate(zip(chunks, vectors)):
            content_hash = _hash(content)
            chunk_rows.append({
                "chunk_id": f"{pk}#{index}-{content_hash[:12]}", "document_pk": pk,
                "document_id": doc["id"], "version": doc["version"], "chunk_index": index,
                "title": doc["title"], "content": content, "metadata_json": metadata,
                "content_hash": content_hash, "embedding": vector,
                "embedding_provider": self.embedding_provider.kind, "embedding_model": self.embedding_provider.model,
                "embedding_dimensions": self.embedding_provider.dimensions,
            })
        fingerprint = {
            "document": doc,
            "index_profile": {
                "chunker": "paragraph-500-overlap-60-v1",
                "embedding_provider": self.embedding_provider.kind,
                "embedding_model": self.embedding_provider.model,
                "embedding_dimensions": self.embedding_provider.dimensions,
            },
        }
        return {"document": doc, "content_hash": _hash(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True)), "chunks": chunk_rows}


def split_text(content: str, max_chars: int = 500, overlap: int = 60) -> list[str]:
    text = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind("。", start + max_chars // 2, end), text.rfind("；", start + max_chars // 2, end))
            if boundary > start:
                end = boundary + 1
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
