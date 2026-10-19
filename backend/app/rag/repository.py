"""Current-source retrieval snapshots and migration-independent historical reads."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import RagDocument, RagChunk, RagIndexProjection
from app.repository import DataSourceUnavailableError
from app.rag.contracts import RagIndexUnavailable, RagIndexConflict
from app.rag.source import KnowledgeSource
from app.rag.index_store import RagIndexStore, assert_immutable, validate_projection
from app.rag.lifecycle import select_versions, merge_removal_barriers
from app.rag.identity import document_key, source_version_hash, profile_hash, embedding_profile, digest
from app.rag.migration import require_rag_ready
from app.runtime.contracts import RuntimeFailure
from app.rag.storage_errors import storage_errors


class RagRepository:
    def __init__(self, source=None, index_store=None):
        self.source = source or KnowledgeSource()
        self.index_store = index_store or RagIndexStore()

    @storage_errors
    def retrieval_snapshot(self, knowledge_types=None, *, on_date=None, budget=None, desired_profile=None):
        require_rag_ready(db.get_engine())
        source = self.source.snapshot(on_date=on_date, budget=budget)
        state = self.index_store.read_snapshot(documents=source.documents)
        from app.rag.snapshot import build_retrieval_snapshot
        return build_retrieval_snapshot(source,state,knowledge_types=knowledge_types,desired_profile=desired_profile,budget=budget)

    def active_chunks(self, knowledge_types=None):
        return self.retrieval_snapshot(knowledge_types)['chunks']

    def index_status(self, *, on_date=None):
        from app.rag.embeddings import resolve_embedding_provider
        try:desired=embedding_profile(resolve_embedding_provider())
        except ValueError as exc:raise RagIndexUnavailable('configuration_error') from exc
        try:return self.retrieval_snapshot(on_date=on_date, desired_profile=desired)['index']
        except RagIndexConflict as exc:return {'indexStatus':'conflict','reasonCode':exc.code,'indexBatchId':None}

    @storage_errors
    def get_document(self, document_id, version=None):
        # Only pre-A06 columns in this query: works before DDL or after partial DDL.
        names=('pk','document_id','version','title','knowledge_type','status','content','metadata_json')
        columns=[getattr(RagDocument,k) for k in names]
        with db.make_session() as session:
            stmt=select(*columns).where(RagDocument.document_id==document_id)
            stmt=stmt.where(RagDocument.version==version) if version is not None else stmt.order_by(RagDocument.version.desc()).limit(1)
            row=session.execute(stmt).mappings().first()
            if row is None:return None
            old=session.execute(select(RagChunk.chunk_id,RagChunk.chunk_index,RagChunk.content).where(RagChunk.document_pk==row['pk']).order_by(RagChunk.chunk_index)).all()
            chunks={c.chunk_id:{'chunk_id':c.chunk_id,'index':c.chunk_index,'content':c.content} for c in old}
            legacy=True; active=None; present=None; eligibility='unknown'
            try:require_rag_ready(db.get_engine());ready=True
            except RagIndexUnavailable:ready=False
            if ready:
                sha=session.execute(select(RagDocument.source_version_hash).where(RagDocument.pk==row['pk'])).scalar()
                legacy=sha is None
                for projection in session.scalars(select(RagIndexProjection).where(RagIndexProjection.document_pk==row['pk'])):
                    for c in projection.chunks_json:
                        if c['chunk_id'] in chunks and digest(chunks[c['chunk_id']]['content']) != c['content_hash']:
                            raise RagIndexUnavailable('chunk_identity_conflict')
                        chunks[c['chunk_id']]={'chunk_id':c['chunk_id'],'index':c['chunk_index'],'content':c['content']}
                try:
                    snapshot=self.source.snapshot();present=any(document_key(d)==row['pk'] for d in snapshot.documents)
                    current=self.retrieval_snapshot()
                    active=any(c['document_id']==document_id and c['version']==row['version'] for c in current['chunks'])
                    eligibility='eligible' if active else 'not_current'
                except (RagIndexUnavailable,RagIndexConflict,RuntimeFailure):pass
            return {'id':row['document_id'],'version':row['version'],'title':row['title'],'knowledge_type':row['knowledge_type'],
                'status':row['status'],'content':row['content'],'active':active,'metadata':deepcopy(row['metadata_json']),
                'chunks':sorted(chunks.values(),key=lambda c:(c['index'],c['chunk_id'])),
                'currentEligibility':eligibility,'sourcePresent':present,'legacyUnknown':legacy}

    @storage_errors
    def count(self, target):
        with db.make_session() as session:
            if target=='documents':return int(session.scalar(select(func.count()).select_from(RagDocument)))
            ids=set(session.scalars(select(RagChunk.chunk_id)))
            try:require_rag_ready(db.get_engine());ready=True
            except RagIndexUnavailable:ready=False
            if ready:
                for projection in session.scalars(select(RagIndexProjection)):
                    ids.update(c['chunk_id'] for c in projection.chunks_json)
            return len(ids)

    @staticmethod
    def _chunk_dict(chunk: RagChunk, document: RagDocument) -> dict[str, Any]:
        metadata = dict(chunk.metadata_json or {})
        return {
            "chunk_id": chunk.chunk_id, "document_id": chunk.document_id, "version": chunk.version,
            "chunk_index": chunk.chunk_index, "title": chunk.title, "content": chunk.content,
            "knowledge_type": document.knowledge_type, "source_type": metadata.get("source_type", ""),
            "source_ref": metadata.get("source_ref", ""), "source_url": metadata.get("source_url", ""),
            "metric_keys": metadata.get("metric_keys", []), "concept_ids": metadata.get("concept_ids", []),
            "aliases": metadata.get("aliases", []), "embedding": chunk.embedding,
            "evidence_level": (metadata.get("governance") or {}).get("evidence_level"),
            "embedding_provider": chunk.embedding_provider, "embedding_model": chunk.embedding_model,
        }
