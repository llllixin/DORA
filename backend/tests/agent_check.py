"""agent_check（迭代 42）：工具层 / 知识检索 / 运行记录 / Dora Chat SSE。

运行：cd backend && python3 -m tests.agent_check
前置：PostgreSQL 已 seed + 后端 API 在 :8000（检索/问答段走 HTTP）。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

from app.repository import Repository
from app.seed import run_seed

BASE = os.environ.get("DORA_API_BASE", "http://localhost:8000/api")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕本地代理（P 系列）


def _http(method: str, path: str, payload: dict | None = None, timeout: int = 15):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def _sse(path: str, payload: dict):
    """读取 SSE 响应为 [(event, data), ...]。"""
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    events = []
    with opener.open(req, timeout=20) as r:
        for chunk in r.read().decode().split("\n\n"):
            ev, data = None, None
            for line in chunk.splitlines():
                if line.startswith("event: "):
                    ev = line[len("event: "):]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
            if ev:
                events.append((ev, data))
    return events


def section1_tools() -> None:
    """1.x query_metric：命中 + 未知指标空数组。"""
    st, body = _http("GET", "/tools/query_metric?metric_key=margin")
    assert st == 200 and body["ok"] and body["count"] > 0, body
    assert {"metric_key", "label", "dimension", "value", "unit"} <= set(body["rows"][0]), body["rows"][0]
    st, body = _http("GET", "/tools/query_metric?metric_key=not_exist")
    assert st == 200 and body["count"] == 0 and body["rows"] == [], body
    print("[1] query_metric OK（margin 命中 / 未知指标空数组）")


def section2_search(repo: Repository) -> None:
    """2.x knowledge/search：命中 references 可回溯；无关词 empty。"""
    from app.action import flow
    repo.create_action_case(
        case={"id": "agent-test", "kind": "problem", "code": "AGT-0001",
              "case_title": "Agent 检索测试档案", "tag_cls": "red", "source": "测试"},
        steps=[{"seq": 0, "title": "A", "desc": "d", "evidence": "e", "status": "pending"}],
        status="open")
    flow.start_step(repo, "agent-test", 0)
    flow.done_step(repo, "agent-test", 0)
    flow.verify(repo, "agent-test", "resolved", note="Agent 检索测试结论")
    try:
        st, body = _http("POST", "/knowledge/search", {"query": "Agent 检索测试", "top_k": 3})
        assert st == 200, body
        assert body["empty"] is False and body["hits"], body
        assert body["references"] and body["references"][0]["source_id"] == "agent-test", body["references"]
        st, empty = _http("POST", "/knowledge/search", {"query": "zzz-无关词-zzz", "top_k": 3})
        assert empty["empty"] is True and empty["hits"] == [] and empty["references"] == [], empty
    finally:
        repo.delete_knowledge_by_source("problem", "agent-test")
        repo.delete_action_case("agent-test")
    print("[2] knowledge/search OK（命中 references 可回溯 / 无关词 empty）")


def section3_runs(repo: Repository) -> None:
    """3.x agent/runs：create/get/append + 404。"""
    repo.delete_all_agent_runs()
    st, body = _http("POST", "/agent/runs",
                     {"trigger": "manual", "input": {"q": "t"}, "events": [{"type": "thought_step"}]})
    run_id = body["run"]["id"]
    assert st == 200 and re.fullmatch(r"r-[0-9a-f]{12}", run_id), run_id
    st, got = _http("GET", f"/agent/runs/{run_id}")
    assert got["run"]["input"] == {"q": "t"} and len(got["run"]["events"]) == 1, got
    st, appended = _http("POST", f"/agent/runs/{run_id}/events", {"event": {"type": "answer"}})
    assert len(appended["run"]["events"]) == 2, appended
    try:
        _http("GET", "/agent/runs/r-notexist0000")
        raise AssertionError("missing run should 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404, exc.code
    print("[3] agent/runs OK（create/get/append + 404）")


def section4_chat(repo: Repository) -> None:
    """4.x dora/chat：5 类事件 + run 落库 + 数字锁。"""
    events = _sse("/dora/chat", {"question": "为什么利润率会失速？", "page": "insight", "insight_id": "p1"})
    types = [e for e, _ in events]
    for t in ("thought_step", "tool_call", "evidence", "answer", "done"):
        assert t in types, types
    answer = next(d for e, d in events if e == "answer")
    assert answer["number_source"] == "engine" and answer["text"].strip(), answer
    done = next(d for e, d in events if e == "done")
    st, run = _http("GET", f"/agent/runs/{done['run_id']}")
    assert run["run"]["trigger"] == "chat", run
    # 数字锁：答案中的数字必须来自该洞察的引擎 payload
    st, engine = _http("GET", "/engine/run")
    ins = next(i for i in engine["insights"] if i["id"] == "p1")
    allowed = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(ins, ensure_ascii=False)))
    used = set(re.findall(r"\d+(?:\.\d+)?", answer["text"]))
    assert used <= allowed, f"answer numbers not from engine: {used - allowed}"
    repo.delete_all_agent_runs()
    print("[4] dora/chat OK（5 类事件 + run 落库 + 数字锁）")


def main() -> int:
    run_seed()
    repo = Repository()
    section1_tools()
    section2_search(repo)
    section3_runs(repo)
    section4_chat(repo)
    print("agent_check OK（工具层 / 知识检索 / 运行记录 / 问答流 4 节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
