"""洞察语义缓存刷新（V3-T2）：用 ReasoningProvider 生成并写入 insight_reasoning。"""
from datetime import datetime, timezone

from app.reasoning.provider import ReasoningContext, resolve_provider


def _context_from_insight(insight: dict, snapshot: dict) -> ReasoningContext:
    return ReasoningContext(
        insight_id=insight["id"],
        insight_type=insight["type"],
        metric=insight["metric"],
        delta=insight["delta"],
        trigger=insight["trigger"],
        factors=insight["factors"],
        question=insight["question"],
        snapshot=snapshot,
    )


def refresh(repo, insights: list[dict], snapshot: dict, provider=None) -> dict:
    """对洞察逐条调用 provider 并写入缓存；返回 updated/fallback。幂等（upsert）。"""
    p = provider or resolve_provider()
    updated: list[str] = []
    fallback: list[str] = []
    for ins in insights:
        try:
            result = p.explain(_context_from_insight(ins, snapshot))
            if not result.semantics:
                fallback.append(ins["id"])
                continue
            generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            repo.upsert_reasoning(
                insight_id=ins["id"],
                semantics=result.semantics,
                provider=result.provider,
                generated_at=generated_at,
            )
            updated.append(ins["id"])
        except Exception as exc:  # provider 出错 → 该条进 fallback（不阻塞其余）
            print(f"[reasoning.refresh] {ins['id']} provider error: {exc}")
            fallback.append(ins["id"])
    return {"updated": updated, "fallback": fallback, "provider": p.kind}
