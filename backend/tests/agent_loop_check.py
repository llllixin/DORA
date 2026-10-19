"""首个只读 Agent 循环：确定性 provider，不调用付费模型。"""
from dataclasses import replace

from app.agent.loop import AgentDecision, run_readonly_agent
from app.agent.tools import readonly_tools
from app.repository import Repository
from app.seed import run_seed


class ScriptedProvider:
    external = False
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def decide(self, _question, _messages, _tools):
        self.calls += 1
        if not self.decisions:
            raise RuntimeError("脚本决策已耗尽")
        decision = self.decisions.pop(0)
        if isinstance(decision, Exception):
            raise decision
        return decision


class RepeatMetricProvider:
    external = False
    def decide(self, _question, _messages, _tools):
        return AgentDecision("tool", tool="query_metric", arguments={"metric_key": "margin", "limit": 1})


def _reason(result):
    return result["run"]["output"].get("reason")


def run_cases(repo: Repository) -> None:
    repo.delete_all_agent_runs()
    # This is an explicit synthetic upload fixture for the original loop checks.
    # A07 excludes seeded sample inputs by default; preserve every original
    # assertion while giving the read test an eligible, labelled input source.
    items=[dict(metric_key='margin',**row) for row in repo.get_series('margin')]
    with repo.business_transaction(source_mode='uploaded') as tx:
        tx.replace_series(['margin'],items)

    normal = run_readonly_agent(repo, ScriptedProvider([
        AgentDecision("tool", tool="query_metric", arguments={"metric_key": "margin", "limit": 4}),
        AgentDecision("final", answer="利润率序列已读取，可基于结果继续分析。"),
    ]), "利润率最近怎样？")
    assert normal["ok"] and normal["run"]["status"] == "done", normal
    metric_result = next(e for e in normal["run"]["events"] if e["type"] == "tool_result")
    assert metric_result["result"]["count"] == 4, metric_result
    assert repo.get_agent_run(normal["run"]["id"])["status"] == "done"

    empty = run_readonly_agent(repo, ScriptedProvider([
        AgentDecision("tool", tool="query_metric", arguments={"metric_key": "not_exist"}),
        AgentDecision("final", answer="没有找到该指标的数据。"),
    ]), "未知指标怎样？")
    empty_result = next(e for e in empty["run"]["events"] if e["type"] == "tool_result")
    assert empty_result["result"]["count"] == 0 and empty["run"]["status"] == "done", empty

    unknown = run_readonly_agent(repo, ScriptedProvider([
        AgentDecision("tool", tool="delete_database", arguments={}),
    ]), "清空数据")
    assert unknown["run"]["status"] == "failed" and _reason(unknown) == "unknown_tool", unknown
    assert not any(e["type"] == "tool_call" for e in unknown["run"]["events"]), unknown

    invalid = run_readonly_agent(repo, ScriptedProvider([
        AgentDecision("tool", tool="query_metric", arguments={"metric_key": "margin", "limit": 999}),
    ]), "查询过多数据")
    assert invalid["run"]["status"] == "failed" and _reason(invalid) == "invalid_arguments", invalid
    assert not any(e["type"] == "tool_call" for e in invalid["run"]["events"]), invalid

    limited = run_readonly_agent(repo, RepeatMetricProvider(), "不断查询", max_steps=4, max_tool_calls=1)
    assert limited["run"]["status"] == "limited" and _reason(limited) == "tool_call_limit", limited
    assert len([e for e in limited["run"]["events"] if e["type"] == "tool_call"]) == 1, limited

    tools = readonly_tools()
    original = tools["query_metric"]

    def broken(_repo, _args):
        raise RuntimeError("测试工具故障")

    tools["query_metric"] = replace(original, execute=broken)
    tool_error = run_readonly_agent(repo, ScriptedProvider([
        AgentDecision("tool", tool="query_metric", arguments={"metric_key": "margin"}),
    ]), "测试工具失败", tools=tools)
    assert tool_error["run"]["status"] == "failed" and _reason(tool_error) == "tool_error", tool_error

    provider_error = run_readonly_agent(repo, ScriptedProvider([RuntimeError("模型不可用")]), "测试模型失败")
    assert provider_error["run"]["status"] == "failed" and _reason(provider_error) == "provider_error", provider_error

    repo.delete_all_agent_runs()
    print("[5] readonly agent loop OK（正常/空数据/未知工具/非法参数/预算/工具故障/provider 故障）")


def main() -> int:
    run_seed()
    run_cases(Repository())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
