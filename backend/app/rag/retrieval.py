"""关键词 + 向量 + RRF 的确定性混合检索。"""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.rag.embeddings import EmbeddingProvider, cosine, resolve_embedding_provider, text_features
from app.rag.ontology import Ontology
from app.rag.repository import RagRepository
from app.runtime.executor import RunContext, invoke_provider, classify
from app.runtime import records

ALLOWED_TYPES = {"glossary", "rule", "procedure", "case", "external"}


class HybridRetriever:
    def __init__(self, repository: RagRepository | None = None, embedding_provider: EmbeddingProvider | None = None,
                 ontology: Ontology | None = None):
        self.repository = repository or RagRepository()
        self.embedding_provider = embedding_provider or resolve_embedding_provider()
        self.ontology = ontology or Ontology.load()

    def search(self, query: str, top_k: int = 5, knowledge_types: list[str] | None = None, *, run_context=None) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        if top_k < 1 or top_k > 20:
            raise ValueError("top_k 必须在 1 到 20 之间")
        if knowledge_types and any(t not in ALLOWED_TYPES for t in knowledge_types):
            raise ValueError("knowledge_types 包含非法值")
        if run_context is None:
            run = RunContext('rag-search', external=getattr(self.embedding_provider, 'external', False) is True,
                             repository=records.default_repository())
            try: return run.finish(self.search(query, top_k, knowledge_types, run_context=run))
            except Exception as exc:
                run.finish({'reason': classify(exc).category}, 'failed'); raise
        run_context.budget.check()
        expansion = self.ontology.expand(query)
        if expansion["semanticStatus"] == "clarification_required":
            return {"query": query, "normalized": expansion, "empty": True, "hits": []}
        expanded_query = " ".join([query, *expansion["terms"]])
        index_snapshot = None
        if hasattr(self.repository, 'retrieval_snapshot'):
            from app.rag.identity import embedding_profile
            snapshot = self.repository.retrieval_snapshot(knowledge_types, budget=run_context.budget,
                                                          desired_profile=embedding_profile(self.embedding_provider))
            chunks = snapshot['chunks']; index_snapshot = snapshot['index']
        else:
            chunks = self.repository.active_chunks(knowledge_types)
        if not chunks:
            return {"query": query, "normalized": expansion, "empty": True, "hits": [], 'index': index_snapshot}
        vector = None; fallback_reason = None
        try:
            from app.rag.identity import embedding_profile, profile_hash
            expected_profile = profile_hash(embedding_profile(self.embedding_provider))
            if any(c.get('embedding_provider') != self.embedding_provider.kind or
                   c.get('embedding_model') != self.embedding_provider.model or
                   (c.get('embedding_profile_hash') and c['embedding_profile_hash'] != expected_profile) or
                   len(c['embedding']) != self.embedding_provider.dimensions for c in chunks):
                from app.runtime.contracts import RuntimeFailure
                raise RuntimeFailure('embedding_profile_mismatch')
            start=len(run_context.events)
            vectors=invoke_provider(self.embedding_provider, 'embed', ([expanded_query],), run_context, 'query_embedding')
            import math
            from app.runtime.contracts import RuntimeFailure
            if (not isinstance(vectors,list) or len(vectors)!=1 or not isinstance(vectors[0],list) or
                len(vectors[0])!=self.embedding_provider.dimensions or
                not all(type(x) in (int,float) and math.isfinite(x) for x in vectors[0])):
                raise RuntimeFailure('invalid_vector')
            attempts=[e for e in run_context.events[start:] if e.get('type')=='model_attempt' and e.get('status')=='done']
            if any(e.get('responseModel') is not None and e['responseModel']!=self.embedding_provider.model for e in attempts):
                raise RuntimeFailure('embedding_profile_mismatch')
            vector=vectors[0]
        except Exception as exc:
            run_context.budget.check()
            fallback_reason = classify(exc).category
            run_context.fallback(fallback_reason)
        lexical: list[tuple[float, str]] = []
        semantic: list[tuple[float, str]] = []
        by_id = {c["chunk_id"]: c for c in chunks}
        raw_scores: dict[str, dict[str, float]] = {}
        for chunk in chunks:
            corpus = " ".join([chunk["title"], chunk["content"], *chunk["aliases"], *chunk["concept_ids"]])
            lex = lexical_score(query, corpus)
            if set(expansion["concept_ids"]) & set(chunk["concept_ids"]):
                lex = min(1.0, lex + 0.25)
            vec = max(0.0, cosine(vector, chunk["embedding"])) if vector is not None else 0.0
            raw_scores[chunk["chunk_id"]] = {"lexical": lex, "vector": vec}
            if lex > 0:
                lexical.append((lex, chunk["chunk_id"]))
            if vec > 0:
                semantic.append((vec, chunk["chunk_id"]))
        lexical.sort(key=lambda item: (-item[0], item[1]))
        semantic.sort(key=lambda item: (-item[0], item[1]))
        lexical_rank = {cid: rank for rank, (_, cid) in enumerate(lexical, 1)}
        semantic_rank = {cid: rank for rank, (_, cid) in enumerate(semantic, 1)}
        fused: list[tuple[float, str]] = []
        for cid in by_id:
            # 向量只参与已存在可解释词法信号的候选排序，防止无关最近邻强行作答。
            if raw_scores[cid]["lexical"] < 0.16:
                continue
            score = 0.0
            if cid in lexical_rank:
                score += 1.0 / (60 + lexical_rank[cid])
            if cid in semantic_rank:
                score += 1.0 / (60 + semantic_rank[cid])
            fused.append((score, cid))
        fused.sort(key=lambda item: (-item[0], item[1]))
        hits = []
        for rrf, cid in fused[:top_k]:
            chunk = {k: v for k, v in by_id[cid].items() if k != "embedding"}
            chunk.update({
                "score": round(rrf, 6), "lexical_score": round(raw_scores[cid]["lexical"], 6),
                "vector_score": round(raw_scores[cid]["vector"], 6), "retrieval": "hybrid" if vector is not None else 'lexical',
            })
            hits.append(chunk)
        run_context.budget.check()
        result = {"query": query, "normalized": expansion, "empty": not hits, "hits": hits}
        if index_snapshot is not None: result['index'] = index_snapshot
        if fallback_reason: result['fallbackReason'] = fallback_reason
        return result


def lexical_score(query: str, text: str) -> float:
    q = text_features(query)
    t = Counter(text_features(text))
    if not q:
        return 0.0
    # 去重后计算覆盖率；高频通用二字词不会因重复被放大。
    unique_q = set(q)
    matched = sum(1 for token in unique_q if t[token] > 0)
    coverage = matched / len(unique_q)
    exact_bonus = 0.2 if query.lower() in text.lower() else 0.0
    return min(1.0, coverage + exact_bonus)
