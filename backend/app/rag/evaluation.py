"""固定问题集评价与发布门禁。"""
from __future__ import annotations

from statistics import mean
from math import ceil
from typing import Any

from app.rag.contracts import load_eval_set
from app.rag.answer import NUMBER_RE
from app.rag.service import RagService

THRESHOLDS = {
    "recall_at_5": 0.80,
    "citation_validity": 1.0,
    "abstain_accuracy": 1.0,
    "tool_route_accuracy": 1.0,
    "unsupported_answers": 0,
}
REALTIME_CASES = [
    ("今天利润率是多少？", "query_metric", "margin"),
    ("现在退货率是多少？", "query_metric", "returns"),
    ("最新订单数是多少？", "query_metric", "orders"),
]


def evaluate(service: RagService | None = None, profile: str = "ontology-v2") -> dict[str, Any]:
    rag = service or RagService()
    rows = load_eval_set(profile)
    details: list[dict[str, Any]] = []
    retrieval_hits = 0
    reciprocal_ranks: list[float] = []
    answered_count = citation_valid_count = 0
    abstain_total = abstain_ok = unsupported = 0
    clarification_total = clarification_ok = 0
    context_chars=[];selected_chars=[]
    for row in rows:
        expected = set(row["expected_document_ids"])
        result = rag.answer(row["query"], top_k=5)
        hits = [h["document_id"] for h in result.get("retrieval", {}).get("hits", [])]
        context=result.get('retrieval',{}).get('hits',[])
        body_chars=sum(len(h['content']) for h in context)
        selected=sum(len(h['content']) for h in context[:2])
        if result['status']=='answered':context_chars.append(body_chars);selected_chars.append(selected)
        recall_hit = True
        rr = 0.0
        if expected:
            recall_hit = any(doc_id in expected for doc_id in hits)
            retrieval_hits += int(recall_hit)
            rank = next((i for i, doc_id in enumerate(hits, 1) if doc_id in expected), None)
            rr = 1.0 / rank if rank else 0.0
            reciprocal_ranks.append(rr)
            answered_count += 1
            cited = {c["document_id"] for c in result.get("citations", [])}
            cited_chunks = {
                c["chunk_id"] for c in result.get("citations", [])
            }
            context_by_id = {
                h["chunk_id"]: f"{h['title']} {h['content']}"
                for h in result.get("retrieval", {}).get("hits", [])
            }
            evidence_text = " ".join(context_by_id[cid] for cid in cited_chunks if cid in context_by_id)
            numbers_grounded = set(NUMBER_RE.findall(result.get("answer", ""))).issubset(
                set(NUMBER_RE.findall(evidence_text))
            )
            citation_ok = (
                result["status"] == "answered" and bool(cited)
                and cited.issubset(set(hits)) and numbers_grounded
            )
            citation_valid_count += int(citation_ok)
            if result["status"] == "answered" and not citation_ok:
                unsupported += 1
        elif row["expected_status"] == "clarification_required":
            clarification_total += 1
            clarification_ok += int(result["status"] == "clarification_required" and not result.get("citations"))
            if result["status"] == "answered":
                unsupported += 1
        else:
            abstain_total += 1
            abstain_ok += int(result["status"] == "abstained")
            if result["status"] == "answered":
                unsupported += 1
        details.append({
            "id": row["id"], "status": result["status"], "expected_status": row["expected_status"],
            "expected_document_ids": sorted(expected), "hit_document_ids": hits,
            "recall_hit": recall_hit, "reciprocal_rank": round(rr, 6),
            "citation_and_numbers_grounded": citation_ok if expected else True,
            'contextBodyChars':body_chars,'templateSelectedBodyChars':selected,
            'index':result.get('retrieval',{}).get('index'),
        })
    route_details = []
    route_ok = 0
    for query, tool, metric in REALTIME_CASES:
        result = rag.answer(query)
        ok = result["status"] == "tool_required" and result.get("tool") == tool and result.get("tool_args", {}).get("metric_key") == metric
        route_ok += int(ok)
        route_details.append({"query": query, "ok": ok, "status": result["status"], "tool": result.get("tool")})
    retrieval_total = sum(1 for row in rows if row["expected_document_ids"])
    metrics = {
        "questions": len(rows),
        "recall_at_5": round(retrieval_hits / retrieval_total, 6) if retrieval_total else 0.0,
        "mrr": round(mean(reciprocal_ranks), 6) if reciprocal_ranks else 0.0,
        "citation_validity": round(citation_valid_count / answered_count, 6) if answered_count else 0.0,
        "abstain_accuracy": round(abstain_ok / abstain_total, 6) if abstain_total else 0.0,
        "tool_route_accuracy": round(route_ok / len(REALTIME_CASES), 6),
        "unsupported_answers": unsupported,
        "retrieval_questions": retrieval_total,
        "clarification_questions": clarification_total,
        "clarification_accuracy": round(clarification_ok / clarification_total, 6) if clarification_total else None,
    }
    passed = (
        metrics["recall_at_5"] >= THRESHOLDS["recall_at_5"]
        and metrics["citation_validity"] >= THRESHOLDS["citation_validity"]
        and metrics["abstain_accuracy"] >= THRESHOLDS["abstain_accuracy"]
        and metrics["tool_route_accuracy"] >= THRESHOLDS["tool_route_accuracy"]
        and metrics["unsupported_answers"] == THRESHOLDS["unsupported_answers"]
        and clarification_ok == clarification_total
    )
    def distribution(values):
        ordered=sorted(values)
        return {'mean':round(mean(ordered),3) if ordered else 0,'p95':ordered[ceil(len(ordered)*.95)-1] if ordered else 0}
    return {"profile": profile, "passed": passed, "thresholds": THRESHOLDS, "metrics": metrics, "details": details, "realtime_details": route_details,
            'strategyProfile':'lexical-gated-rrf-v1','contextBodyChars':distribution(context_chars),
            'templateSelectedBodyChars':distribution(selected_chars),
            "intentionalChanges": [{"id": row["id"], "reason": row["reason"]} for row in rows if "reason" in row]}
