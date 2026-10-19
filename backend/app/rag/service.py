"""完整 RAG 编排：索引、检索、实时分流、回答、引用与运行记录。"""
from __future__ import annotations

from typing import Any

from app.rag.answer import RagAnswerProvider, TemplateAnswerProvider, resolve_answer_provider, validate_citations
from app.rag.embeddings import EmbeddingProvider, resolve_embedding_provider
from app.rag.indexer import RagIndexer
from app.rag.ontology import Ontology
from app.rag.repository import RagRepository
from app.rag.retrieval import HybridRetriever, ALLOWED_TYPES
from app.repository import Repository
from app.runtime.executor import RunContext, invoke_provider, classify
from app.runtime.contracts import RuntimeFailure

REALTIME_TERMS = ("今天", "现在", "当前", "最新", "刚刚", "实时", "此刻")
SENSITIVE_TERMS = ("密码", "口令", "身份证", "密钥", "secret", "token")


class RagService:
    def __init__(self, rag_repository: RagRepository | None = None, run_repository: Repository | None = None,
                 embedding_provider: EmbeddingProvider | None = None, answer_provider: RagAnswerProvider | None = None,
                 ontology: Ontology | None = None):
        self.rag_repository = rag_repository or RagRepository()
        self.run_repository = run_repository or Repository()
        self.embedding_provider = embedding_provider or resolve_embedding_provider()
        self.answer_provider = answer_provider or resolve_answer_provider()
        self.ontology = ontology or Ontology.load()
        self.indexer = RagIndexer(self.rag_repository, self.embedding_provider, self.run_repository)
        self.retriever = HybridRetriever(self.rag_repository, self.embedding_provider, self.ontology)

    def rebuild_index(self, documents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self.indexer.rebuild(documents)

    def search(self, query: str, top_k: int = 5, knowledge_types: list[str] | None = None, *, run_context=None) -> dict[str, Any]:
        self._validate(query, top_k, knowledge_types)
        run = run_context or RunContext('rag-search', external=getattr(self.embedding_provider, 'external', False) is True,
                                         repository=self.run_repository, input_data={'query': query})
        try:
            value = self.retriever.search(query, top_k, knowledge_types, run_context=run)
            return value if run_context else run.finish(value)
        except Exception as exc:
            if not run_context:
                run.finish({'reasonCode':getattr(exc,'code',classify(exc).category)}, 'failed')
                exc.run_id=run.run_id
            raise

    @staticmethod
    def _validate(question, top_k, knowledge_types):
        if not (question or '').strip(): raise ValueError('question/query 不能为空')
        if type(top_k) is not int or not 1 <= top_k <= 20: raise ValueError('top_k 必须在 1 到 20 之间')
        if knowledge_types and any(t not in ALLOWED_TYPES for t in knowledge_types): raise ValueError('knowledge_types 包含非法值')

    def answer(self, question: str, top_k: int = 5, knowledge_types: list[str] | None = None, *, run_context=None) -> dict[str, Any]:
        question = (question or "").strip()
        self._validate(question, top_k, knowledge_types)
        run = run_context or RunContext('rag-answer', external=any(getattr(p, 'external', False) is True for p in
            (self.embedding_provider, self.answer_provider)), repository=self.run_repository,
            input_data={"question": question, "top_k": top_k, "knowledge_types": knowledge_types or []})
        run_id = run.run_id
        def complete(output, status='done'):
            return {'run_id': run_id, **run.finish(output, status)}
        if any(term.lower() in question.lower() for term in SENSITIVE_TERMS):
            output = {"status": "abstained", "answer": "知识库不提供凭据或个人敏感信息。", "citations": [], "retrieval": {"query": question, "empty": True, "hits": []}}
            self.run_repository.append_agent_run_event(run_id, {"type": "policy", "data": {"reason": "sensitive_information"}})
            return complete(output)
        realtime = any(term in question for term in REALTIME_TERMS)
        semantics = self.ontology.resolve(question, "metric" if realtime else "knowledge")
        if semantics["semanticStatus"] == "clarification_required":
            output = {
                "status": "clarification_required",
                "answer": " ".join(dict.fromkeys(item["question"] for item in semantics["ambiguities"])),
                "citations": [], "semantics": semantics,
                "retrieval": {"query": question, "empty": True, "hits": []},
            }
            self.run_repository.append_agent_run_event(run_id, {"type": "clarification", "data": semantics})
            return complete(output)
        route = self._realtime_route(question)
        if route:
            event = {"type": "route", "data": route}
            self.run_repository.append_agent_run_event(run_id, event)
            output = {"status": "tool_required", "answer": "该问题需要读取当前业务数据，不能由知识库作答。", **route, "citations": [], "semantics": semantics}
            if output["status"] == "abstained":
                output["answer"] = "当前知识查询尚未注册此业务读取工具。"
            return complete(output)
        try:
            retrieval = self.search(question, min(top_k, run.profile.maxContextChunks), knowledge_types, run_context=run)
            summary = [{"chunk_id": h["chunk_id"], "document_id": h["document_id"], "score": h["score"]} for h in retrieval["hits"]]
            self.run_repository.append_agent_run_event(run_id, {"type": "retrieval", "data": {"hits": summary}})
            if retrieval["empty"]:
                output = {"status": "abstained", "answer": "知识库暂无足够依据。", "citations": [], "retrieval": retrieval}
                return complete(output)
            if sum(len(h['content']) for h in retrieval['hits']) > run.profile.maxContextChars:
                raise RuntimeFailure('context_limit')
            provider = self.answer_provider
            fallback_reason = retrieval.get('fallbackReason')
            try:
                result = invoke_provider(provider, 'answer', (question, retrieval['hits']), run, 'answer')
                citations = validate_citations(result, retrieval['hits'])
            except Exception as exc:
                run.budget.check()
                fallback_reason = classify(exc).category
                run.fallback(fallback_reason); provider = TemplateAnswerProvider()
                result = invoke_provider(provider, 'answer', (question, retrieval['hits']), run, 'fallback')
                citations = validate_citations(result, retrieval['hits'])
            run.budget.check()
            output = {
                "status": "answered", "answer": result["answer"], "citations": citations,
                "retrieval": retrieval, "provider": provider.kind, "model": provider.model,
            }
            if fallback_reason: output['fallbackReason'] = fallback_reason
            self.run_repository.append_agent_run_event(run_id, {"type": "answer", "data": {"citations": [c["chunk_id"] for c in citations]}})
            return complete(output)
        except Exception as exc:
            from app.rag.contracts import RagIndexConflict, RagIndexUnavailable
            if isinstance(exc, (RagIndexConflict, RagIndexUnavailable)):
                run.finish({'reasonCode': exc.code}, 'failed')
                exc.run_id=run.run_id
                raise
            reason = classify(exc).category
            status = 'limited' if reason in ('budget_exceeded', 'deadline_exceeded', 'context_limit') else 'failed'
            output = {"status": status, "answer": "", "citations": [], "error": reason}
            self.run_repository.append_agent_run_event(run_id, {"type": "error", "data": {"reason": reason}})
            return complete(output, status)

    def get_document(self, document_id: str, version: int | None = None) -> dict[str, Any] | None:
        return self.rag_repository.get_document(document_id, version)

    def _realtime_route(self, question: str) -> dict[str, Any] | None:
        if not any(term in question for term in REALTIME_TERMS):
            return None
        semantics = self.ontology.resolve(question, "metric")
        if semantics["semanticStatus"] == "clarification_required":
            return None
        binding = semantics["metricBinding"]
        if binding:
            return {"tool": "query_metric", "tool_args": {"metric_key": binding["metricKey"], "dimension": binding["dimension"] or ""}}
        if any(self.ontology.concepts[cid]["type"] == "Collection" for cid in semantics["conceptIds"]):
            return {"status": "abstained", "reasonCode": "tool_unavailable", "requestedTool": "read_collection"}
        if "Watch" in question or "关注" in question:
            return {"status": "abstained", "reasonCode": "tool_unavailable", "requestedTool": "list_watch"}
        if "行动" in question or "档案" in question:
            return {"status": "abstained", "reasonCode": "tool_unavailable", "requestedTool": "list_action_cases"}
        return None
