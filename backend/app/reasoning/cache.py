"""洞察语义缓存刷新（V3-T2）：用 ReasoningProvider 生成并写入 insight_reasoning。

兜底（阶段 1，P011/D028）：llm 批量走 预算(20s)+并发(2–3)+熔断+优先级(问题→机会→变化)调度；
template 保持毫秒级串行原语义。返回契约不变 {updated, fallback, provider}。
"""
import time
import inspect
from copy import deepcopy
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

from app.reasoning import policy
from app.reasoning.provider import ReasoningContext, resolve_provider
from app.business_version import incomplete_version, reasoning_input_hash, reprofile_version
from app.runtime.executor import RunContext, invoke_provider, classify
from app.runtime.contracts import RuntimeFailure
from app.db_budget import budget_scope


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


def _attempt(repo, provider, insight: dict, snapshot: dict, run_context=None) -> str:
    """单条尝试（worker 线程内）：成功写缓存返回 'updated'；任何失败返回 'fallback'。"""
    try:
        version = snapshot.get("businessVersion") or incomplete_version()
        if version["versionStatus"] != "complete" or not hasattr(repo, "commit_reasoning_if_current"):
            return "fallback"
        if hasattr(provider, "profile") and reprofile_version(version, provider.profile) != version:
            return "discarded"
        if run_context: run_context.budget.check()
        result = invoke_provider(provider, 'explain', (_context_from_insight(insight, snapshot),), run_context, 'reasoning') if run_context else provider.explain(_context_from_insight(insight, snapshot))
        if not result.semantics:
            return "fallback"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if run_context: run_context.budget.check()
        options = {'commit_guard':run_context.budget.check} if run_context and 'commit_guard' in inspect.signature(repo.commit_reasoning_if_current).parameters else {}
        return repo.commit_reasoning_if_current(version, insight["id"], reasoning_input_hash(insight, snapshot),
                                                result.semantics, result.provider, generated_at, **options)
    except Exception as exc:
        if run_context:
            reason = classify(exc).category
            run_context.emit({'type':'reasoning_fallback', 'insightId':insight['id'], 'fallbackReason':reason})
        return "fallback"


def _refresh_llm(repo, insights: list[dict], snapshot: dict, provider, run_context=None) -> dict:
    """llm 批量：优先级排序 + 预算/并发调度 + 熔断；降级中止后剩余全部 fallback。"""
    ordered = sorted(insights, key=policy.priority_key)
    updated: list[str] = []
    fallback: list[str] = []
    discarded: list[str] = []

    if policy.breaker.is_open():
        fallback.extend(i["id"] for i in ordered)
        return {"updated": updated, "fallback": fallback, "discarded": discarded, "provider": provider.kind}

    budget = policy.budget_secs()
    deadline = time.monotonic() + budget
    if run_context: deadline = min(deadline, run_context.budget.deadline)
    max_workers = min(policy.concurrency(), len(ordered) or 1, run_context.profile.maxConcurrency if run_context else 3)
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
        elif outcome == "discarded":
            discarded.append(ins_id)
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
                fut = ex.submit(_attempt, repo, provider, ins, snapshot, run_context)
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
    return {"updated": updated, "fallback": fallback, "discarded": discarded, "provider": provider.kind}


def _refresh_template(repo, insights: list[dict], snapshot: dict, provider, run_context=None) -> dict:
    updated: list[str] = []
    fallback: list[str] = []
    discarded: list[str] = []
    for ins in insights:
        outcome = _attempt(repo, provider, ins, snapshot, run_context)
        if outcome == "updated":
            updated.append(ins["id"])
        elif outcome == "discarded":
            discarded.append(ins["id"])
        else:
            fallback.append(ins["id"])
    return {"updated": updated, "fallback": fallback, "discarded": discarded, "provider": provider.kind}


def refresh(repo, insights: list[dict], snapshot: dict, provider=None, *, run_context=None) -> dict:
    """对洞察生成语义并写入缓存；幂等（upsert）。llm 走有界调度，template 串行。"""
    p = provider or resolve_provider()
    snapshot = deepcopy(snapshot)
    recording_repo = repo if all(hasattr(repo, name) for name in ("create_agent_run", "append_agent_run_event", "finish_agent_run")) else None
    run = run_context or RunContext('reasoning-refresh', external=getattr(p, 'external', False) is True,
                                    repository=recording_repo, input_data={'insightIds':[i['id'] for i in insights]},
                                    profile=getattr(p, 'budget_profile', None))
    try:
        with budget_scope(run.budget):
            version = snapshot.get("businessVersion") or incomplete_version()
            if hasattr(p, "profile"):
                version = reprofile_version(version, p.profile)
                snapshot["businessVersion"] = version
            if not insights:
                out = {"updated": [], "fallback": [], "discarded": [], "provider": p.kind}
            elif p.kind == "llm":
                out = _refresh_llm(repo, insights, snapshot, p, run)
            else:
                out = _refresh_template(repo, insights, snapshot, p, run)
            current = repo.read_business_inputs().business_version if version["versionStatus"] == "complete" else incomplete_version()
            status = "unversioned" if version["versionStatus"] != "complete" else ("stale" if current["revision"] != version["revision"] else "completed")
            reasons = {e['insightId']:e['fallbackReason'] for e in run.events if e['type']=='reasoning_fallback'}
            limited = any(v in ('budget_exceeded','deadline_exceeded','context_limit') for v in reasons.values())
            output = {**out, "businessVersion": version, "currentRevision": current["revision"], "status": status,
                      'fallbackReasons':reasons, 'budgetStatus':'limited' if limited else 'completed'}
            return run.finish(output, 'limited' if limited else 'done') if run_context is None else {**output, **run.diagnostics()}
    except Exception as exc:
        if run_context is None:
            reason = classify(exc).category
            limited = reason in ('budget_exceeded','deadline_exceeded','context_limit')
            try:
                run.finish({'reason':reason,'status':'failed','budgetStatus':'limited' if limited else 'failed'},
                           'limited' if limited else 'failed')
            except Exception:
                # The caller must see the orchestration failure even when the
                # independent terminal recording attempt also fails.
                pass
        raise
