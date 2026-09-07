"""洞察语义缓存刷新（V3-T2）：用 ReasoningProvider 生成并写入 insight_reasoning。

兜底（阶段 1，P011/D028）：llm 批量走 预算(20s)+并发(2–3)+熔断+优先级(问题→机会→变化)调度；
template 保持毫秒级串行原语义。返回契约不变 {updated, fallback, provider}。
"""
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

from app.reasoning import policy
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


def _attempt(repo, provider, insight: dict, snapshot: dict) -> str:
    """单条尝试（worker 线程内）：成功写缓存返回 'updated'；任何失败返回 'fallback'。"""
    try:
        result = provider.explain(_context_from_insight(insight, snapshot))
        if not result.semantics:
            return "fallback"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        repo.upsert_reasoning(
            insight_id=insight["id"],
            semantics=result.semantics,
            provider=result.provider,
            generated_at=generated_at,
        )
        return "updated"
    except Exception as exc:
        print(f"[reasoning.refresh] {insight['id']} provider error: {exc}")
        return "fallback"


def _refresh_llm(repo, insights: list[dict], snapshot: dict, provider) -> dict:
    """llm 批量：优先级排序 + 预算/并发调度 + 熔断；降级中止后剩余全部 fallback。"""
    ordered = sorted(insights, key=policy.priority_key)
    updated: list[str] = []
    fallback: list[str] = []

    if policy.breaker.is_open():
        fallback.extend(i["id"] for i in ordered)
        return {"updated": updated, "fallback": fallback, "provider": provider.kind}

    budget = policy.budget_secs()
    deadline = time.monotonic() + budget
    max_workers = min(policy.concurrency(), len(ordered) or 1)
    degrade_streak = 0
    break_after = policy.circuit_fails()

    def handle(fut) -> None:
        nonlocal degrade_streak
        ins_id = fut_ins[fut]
        try:
            outcome = fut.result()
        except policy.DegradationError:
            degrade_streak += 1
            fallback.append(ins_id)
            return
        except Exception:
            fallback.append(ins_id)
            return
        if outcome == "updated":
            updated.append(ins_id)
        else:
            fallback.append(ins_id)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        inflight: set = set()
        fut_ins = {}
        idx = 0
        n = len(ordered)

        def stop_early() -> bool:
            return (time.monotonic() > deadline or policy.breaker.is_open()
                    or degrade_streak >= break_after)

        while idx < n:
            if stop_early():
                fallback.extend(i["id"] for i in ordered[idx:])
                break
            # 填满并发槽（每次提交前都检查预算，保证不超界提交新条）
            while len(inflight) < max_workers and idx < n and time.monotonic() <= deadline:
                ins = ordered[idx]
                idx += 1
                fut = ex.submit(_attempt, repo, provider, ins, snapshot)
                fut_ins[fut] = ins["id"]
                inflight.add(fut)
            if idx >= n and not inflight:
                break
            # 等任一完成，回收槽位并记账
            done, _ = wait(inflight, return_when=FIRST_COMPLETED)
            for fut in done:
                inflight.discard(fut)
                handle(fut)
        # 收尾在途任务（单条 ≤ timeout，属可接受在途尾差；逐批取完成结果）
        while inflight:
            done, _ = wait(inflight, return_when=FIRST_COMPLETED)
            for fut in done:
                inflight.discard(fut)
                handle(fut)
    return {"updated": updated, "fallback": fallback, "provider": provider.kind}


def _refresh_template(repo, insights: list[dict], snapshot: dict, provider) -> dict:
    updated: list[str] = []
    fallback: list[str] = []
    for ins in insights:
        try:
            result = provider.explain(_context_from_insight(ins, snapshot))
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
    return {"updated": updated, "fallback": fallback, "provider": provider.kind}


def refresh(repo, insights: list[dict], snapshot: dict, provider=None) -> dict:
    """对洞察生成语义并写入缓存；幂等（upsert）。llm 走有界调度，template 串行。"""
    p = provider or resolve_provider()
    if not insights:
        return {"updated": [], "fallback": [], "provider": p.kind}
    if p.kind == "llm":
        return _refresh_llm(repo, insights, snapshot, p)
    return _refresh_template(repo, insights, snapshot, p)

