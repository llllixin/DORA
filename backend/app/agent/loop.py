"""供应商无关的只读 Agent 有限循环。"""
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.agent.tools import execute_tool, ToolInputError, ToolSpec, readonly_tools
from app.repository import Repository
from app.runtime.executor import RunContext, invoke_provider, classify


@dataclass(frozen=True)
class AgentDecision:
    kind: Literal["tool", "final"]
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str = ""


class AgentProvider(Protocol):
    """模型适配器只负责决策；执行、权限、预算和持久化属于循环。"""

    def decide(
        self,
        question: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AgentDecision: ...


def _append(repo: Repository, run_id: str, event: dict[str, Any]) -> None:
    if repo.append_agent_run_event(run_id, event) is None:
        raise RuntimeError("agent run disappeared")


def _finish(repo: Repository, run_id: str, status: str, output: dict[str, Any]) -> dict[str, Any]:
    run = repo.finish_agent_run(run_id, status, output)
    if run is None:
        raise RuntimeError("agent run disappeared")
    return {"ok": status == "done", "run": run, "output": output}


def _stop(repo: Repository, run_id: str, status: str, reason: str, detail: str = "") -> dict[str, Any]:
    event = {"type": "stop", "status": status, "reason": reason}
    if detail:
        event["detail"] = detail
    _append(repo, run_id, event)
    return _finish(repo, run_id, status, {"reason": reason, "detail": detail})


def run_readonly_agent(
    repo: Repository,
    provider: AgentProvider,
    question: str,
    *,
    max_steps: int = 4,
    max_tool_calls: int = 3,
    tools: dict[str, ToolSpec] | None = None,
    run_context=None,
) -> dict[str, Any]:
    """执行一个可回放的只读 Agent；所有预期失败都返回带终态的运行记录。"""
    question = (question or "").strip()
    if not question:
        raise ValueError("question 不能为空")
    if not 1 <= max_steps <= 8:
        raise ValueError("max_steps 必须在 1..8 之间")
    if not 0 <= max_tool_calls <= 6:
        raise ValueError("max_tool_calls 必须在 0..6 之间")

    registry = tools or readonly_tools()
    schemas = [registry[name].public_schema() for name in sorted(registry)]
    context = run_context or RunContext('readonly-agent', external=getattr(provider, 'external', False) is True,
                                      repository=repo, input_data={'question':question})
    max_steps = min(max_steps, context.profile.maxSteps)
    max_tool_calls = min(max_tool_calls, context.profile.maxToolCalls)
    run_id = context.run_id
    _append(repo, run_id, {'type':'run_started','limits':{'steps':max_steps,'tool_calls':max_tool_calls}})
    def finish(output, status='done'):
        output = context.finish(output, status)
        return {'ok':status=='done','run':repo.get_agent_run(run_id),'output':output}
    def stop(status, reason, detail=''):
        _append(repo, run_id, {'type':'stop','status':status,'reason':reason})
        return finish({'reason':reason,'detail':detail},status)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tool_calls = 0

    for step in range(1, max_steps + 1):
        try:
            context.budget.check()
            decision = invoke_provider(provider, 'decide', (question, list(messages), schemas), context, 'agent_decision')
        except Exception as exc:  # provider 是外部边界，失败必须落可回放终态
            reason = classify(exc).category
            return stop('limited' if reason in ('deadline_exceeded','budget_exceeded','context_limit','provider_timeout') else 'failed', reason)

        if not isinstance(decision, AgentDecision):
            return stop("failed", "invalid_decision")

        if decision.kind == "final":
            answer = decision.answer.strip() if isinstance(decision.answer, str) else ""
            if not answer:
                return stop("failed", "empty_answer")
            _append(repo, run_id, {"type": "answer", "step": step, "text": answer})
            return finish({"answer": answer, "tool_calls": tool_calls})

        if decision.kind != "tool":
            return stop("failed", "invalid_decision")
        if tool_calls >= max_tool_calls:
            return stop("limited", "tool_call_limit")

        spec = registry.get(decision.tool)
        if spec is None:
            return stop("failed", "unknown_tool")
        try:
            arguments = spec.validate(decision.arguments)
        except ToolInputError as exc:
            return stop("failed", "invalid_arguments")

        tool_calls += 1
        _append(repo, run_id, {"type": "tool_call", "step": step, "tool": spec.name, "arguments": arguments})
        try:
            context.budget.check()
            result = context.execute('tool', 'local-tool', spec.name, {'arguments':arguments}, False,
                                     lambda attempt:execute_tool(spec,repo,arguments,run_context=context))
        except Exception as exc:  # 工具异常不可让运行停在 running
            _append(repo, run_id, {"type": "tool_result", "step": step, "tool": spec.name, "status": "error"})
            reason = classify(exc).category
            return stop('limited' if reason in ('deadline_exceeded','budget_exceeded','context_limit') else 'failed',
                        reason if reason in ('deadline_exceeded','budget_exceeded','context_limit') else 'tool_error')

        _append(repo, run_id, {"type": "tool_result", "step": step, "tool": spec.name, "status": "ok", "result": result})
        messages.append({"role": "assistant", "tool": spec.name, "arguments": arguments})
        messages.append({"role": "tool", "tool": spec.name, "result": result})

    return stop("limited", "step_limit")
