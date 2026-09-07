"""V5 action_check：第 1 节 = 领域/持久化 CRUD（T1）；后续节（闭环 E2E）T5 追加。

运行：cd backend && python3 -m tests.action_check
前置：PostgreSQL 已 seed + 后端在运行（第 1 节仅需 DB）。
"""
import sys

from app.repository import Repository
from app.seed import run_seed


def section1_crud(repo: Repository) -> None:
    """V5-T1：seed 迁移幂等 + case/step CRUD 往返。"""
    # 重复 seed 幂等：case=5、每案 5 步、状态分布正确
    run_seed()
    run_seed()
    cases = repo.list_action_cases()
    ids = sorted(c["id"] for c in cases)
    assert ids == ["o1", "o2", "p1", "p2", "p3"], f"seed ids: {ids}"
    codes = {c["id"]: c["code"] for c in cases}
    assert codes == {"p1": "PRF-0831", "p2": "RTN-0816", "p3": "ORD-1022",
                     "o1": "UPC-0418", "o2": "STO-0607"}, codes
    for cid in ids:
        detail = repo.get_action_case(cid)
        steps = detail["steps"]
        assert len(steps) == 5, f"{cid} step count {len(steps)}"
        assert [s["status"] for s in steps[:3]] == ["done", "done", "in_progress"]
        assert [s["status"] for s in steps[3:]] == ["pending", "pending"]
        assert steps[2]["why"], f"{cid} current step should carry why"

    # 步骤状态与档案 CRUD 往返（用独立建档验证，不动 seed 行）
    tmp = repo.create_action_case(
        case={"id": "o-test", "kind": "opportunity", "code": "TST-0001",
              "case_title": "测试机会", "tag_cls": "green", "source": "来源：测试洞察"},
        steps=[{"seq": 0, "title": "发现", "desc": "d", "evidence": "e", "status": "pending"},
               {"seq": 1, "title": "验证", "desc": "d2", "evidence": "e2", "status": "pending"}],
        status="open",
    )
    assert tmp["status"] == "open" and len(tmp["steps"]) == 2
    step = repo.set_action_step_status("o-test", 1, "done", note="核查完成", result="指标恢复")
    assert step is not None and step["status"] == "done" and step["note"] == "核查完成"
    assert step["result"] == "指标恢复" and step["finished_at"], "done step should carry finished_at"
    again = repo.get_action_case("o-test")
    assert again["steps"][1]["status"] == "done" and again["steps"][1]["result"] == "指标恢复"
    try:
        repo.set_action_step_status("o-test", 1, "boom")
        raise AssertionError("invalid step status should raise")
    except ValueError:
        pass
    # verify resolved
    verified = repo.verify_action_case("o-test", "resolved")
    assert verified["status"] == "resolved"
    try:
        repo.create_action_case(case={"id": "o-test"}, steps=[])
        raise AssertionError("duplicate case should raise")
    except ValueError:
        pass
    # 删除级联 + 幂等
    assert repo.delete_action_case("o-test") is True
    assert repo.get_action_case("o-test") is None
    assert repo.count_rows("action_step") == 5 * 5, "seed steps remain 25 after delete tmp"
    assert repo.delete_action_case("o-test") is False
    assert repo.count_rows("action_case") == 5

    # F4：seed 档案进度在 sample（run_seed）后不被覆盖
    from app.seed import action_cases_from_static
    repo.set_action_step_status("o2", 3, "in_progress")  # 人为推进 seed 档案
    run_seed()  # 模拟"载入样例"
    preserved = repo.get_action_case("o2")
    assert preserved["steps"][3]["status"] == "in_progress", "F4: sample must NOT reset seed progress"
    # 复位 o2 基线（门禁自持，保证后续测试可重现；运行时语义=保留进度）
    baseline = next((c, st) for c, st in action_cases_from_static() if c["id"] == "o2")
    repo.upsert_seed_case(baseline[0], baseline[1])
    assert repo.get_action_case("o2")["steps"][3]["status"] == "pending", "o2 baseline restored"


def section2_builder(repo: Repository) -> None:
    """V5-T2：洞察→档案（引擎判定校验 / 幂等 / 模板）。"""
    from app.action.builder import create_case_from_insight
    from app.engine.engine import run_engine

    def engine_by(insight_id: str) -> dict:
        return next(i for i in run_engine(repo)["insights"] if i["id"] == insight_id)

    # 注入跌破 → 引擎产出 problem e2（当前判定集内）
    repo.replace_series(["east_orders"], [
        {"metric_key": "east_orders", "label": f"T{i}", "dimension": "华东",
         "value": float(v), "unit": ""}
        for i, v in enumerate([105.0, 103.0, 100.0, 97.0, 93.0])
    ])
    e2 = engine_by("e2")
    out = create_case_from_insight(repo, e2)
    assert out["created"] is True, "e2 should create new case"
    case = out["case"]
    assert case["kind"] == "problem" and case["id"] == "e2"
    assert case["code"].startswith("PRB-") and case["status"] == "open"
    assert len(case["steps"]) == 4 and case["steps"][0]["status"] == "done"
    assert case["steps"][1]["status"] == "in_progress"

    # 幂等：重复建档返回既有
    again = create_case_from_insight(repo, e2)
    assert again["created"] is False and again["case"]["id"] == "e2"

    # change / 伪造 / 已静态 seed 的 p1（已有档案 → 返回既有 created=False）
    c3 = engine_by("c3")
    assert c3["type"] == "change"
    try:
        create_case_from_insight(repo, c3)
        raise AssertionError("change insight must not be archived")
    except ValueError:
        pass
    try:
        create_case_from_insight(repo, {"id": "w-fake", "type": "problem", "title": "x"})
        raise AssertionError("non-engine id must not be archived")
    except ValueError:
        pass
    p1 = engine_by("p1")
    existing = create_case_from_insight(repo, p1)
    assert existing["created"] is False and existing["case"]["id"] == "p1"

    repo.delete_action_case("e2")
    run_seed()  # 还原


def section3_flow(repo: Repository) -> None:
    """V5-T3：状态机服务层（start/done/blocked/verify + 冻结/非法迁移拒绝）。"""
    from app.action import flow

    # 临时档案：3 步全 pending，走完整链路到 resolved
    created = repo.create_action_case(
        case={"id": "flow-test", "kind": "problem", "code": "TST-0901",
              "case_title": "流程测试", "tag_cls": "red", "source": "测试"},
        steps=[{"seq": 0, "title": "A", "desc": "d", "evidence": "e", "status": "pending"},
               {"seq": 1, "title": "B", "desc": "d", "evidence": "e", "status": "pending"},
               {"seq": 2, "title": "C", "desc": "d", "evidence": "e", "status": "pending"}],
        status="open",
    )
    assert created["status"] == "open"
    # 非法：pending 直接 done
    try:
        flow.done_step(repo, "flow-test", 0)
        raise AssertionError("pending->done must be rejected")
    except flow.ActionFlowError:
        pass
    # start→done 推进
    c1 = flow.start_step(repo, "flow-test", 0)
    assert c1["status"] == "running" and c1["steps"][0]["status"] == "in_progress"
    c2 = flow.done_step(repo, "flow-test", 0, note="A 完成", result="已核对")
    assert c2["steps"][0]["status"] == "done" and c2["steps"][0]["result"] == "已核对"
    # blocked → start 恢复
    flow.start_step(repo, "flow-test", 1)
    c3 = flow.block_step(repo, "flow-test", 1, note="等外部数据")
    assert c3["steps"][1]["status"] == "blocked" and c3["steps"][1]["note"] == "等外部数据"
    c4 = flow.start_step(repo, "flow-test", 1)
    assert c4["steps"][1]["status"] == "in_progress"
    flow.done_step(repo, "flow-test", 1)
    # resolved 需全 done + note：先验（有 pending）应拒绝
    try:
        flow.verify(repo, "flow-test", "resolved", note="x")
        raise AssertionError("resolved before all done must be rejected")
    except flow.ActionFlowError:
        pass
    flow.start_step(repo, "flow-test", 2)
    c5 = flow.done_step(repo, "flow-test", 2, note="全部完成", result="收尾")
    assert c5["status"] == "waiting_verify"
    try:
        flow.verify(repo, "flow-test", "resolved", note="")
        raise AssertionError("resolved without note must be rejected")
    except flow.ActionFlowError:
        pass
    c6 = flow.verify(repo, "flow-test", "resolved", note="利润率回到 18.6%，验证通过")
    assert c6["status"] == "resolved"
    assert "验证通过" in c6["archive"], "verify note should append to archive"
    # 已 resolved 冻结
    for fn, args in ((flow.start_step, (repo, "flow-test", 0)),
                     (flow.done_step, (repo, "flow-test", 0)),
                     (flow.verify, (repo, "flow-test", "resolved", "x"))):
        try:
            fn(*args)
            raise AssertionError("resolved case transitions must be rejected")
        except flow.ActionFlowError:
            pass

    # continue 路径：全 done 后 continue → running（人工继续）
    created2 = repo.create_action_case(
        case={"id": "flow-cont", "kind": "opportunity", "code": "TST-0902", "case_title": "继续测试", "tag_cls": "green", "source": "测试"},
        steps=[{"seq": 0, "title": "A", "desc": "d", "evidence": "e", "status": "pending"}], status="open")
    assert created2["status"] == "open"
    flow.start_step(repo, "flow-cont", 0)
    flow.done_step(repo, "flow-cont", 0)
    cont = flow.verify(repo, "flow-cont", "continue", note="进入下一轮观察")
    assert cont["status"] == "running"

    repo.delete_action_case("flow-test")
    repo.delete_action_case("flow-cont")
    run_seed()  # 还原 seed 状态


def section4_e2e(repo: Repository) -> None:
    """V5-T5：Action 闭环 HTTP E2E（前置：后端在运行）。

    Case4+1：watch→跌破→引擎 e2→建档→步骤 done→verify resolved（note 入 archive）。
    Case2：o1 推进至 waiting_verify → verify continue → running（可复制验证→继续）。
    """
    from tests.e2e_api_check import east_breach_csv, get, post, post_file

    def call(method: str, path: str, payload: dict | None = None):
        import json
        import urllib.error
        import urllib.request
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            'http://localhost:8000/api' + path, data=body, method=method,
            headers={'Content-Type': 'application/json'} if body else {})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def step(cid: str, seq: int, action: str, note: str = "", result: str = ""):
        if action == "start":
            return call("POST", f"/action/cases/{cid}/steps/{seq}/start")
        if action == "blocked":
            return call("POST", f"/action/cases/{cid}/steps/{seq}/blocked", {"note": note})
        return call("POST", f"/action/cases/{cid}/steps/{seq}/done", {"note": note, "result": result})

    def delete(path: str):
        import urllib.request
        req = urllib.request.Request('http://localhost:8000/api' + path, method='DELETE')
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15):
            pass

    post("/datasets/sample")
    # Case4+1：升级 problem e2 → 真实建档 → 完整执行 → resolved
    created_watch = post("/watch", {"text": "帮我关注华东销售额，如果连续三天下降就提醒我", "frequency": "on_update"})
    assert created_watch["ok"]
    watch_id = created_watch["target"]["id"]
    before = get("/action/cases")
    assert not any(c["id"] == "e2" for c in before["cases"]), "e2 not yet judged -> no case"
    up = post_file("/datasets", "east_breach_v4.csv", east_breach_csv())
    assert up.get("ok"), "breach upload failed"
    probs = get("/insights?type=problem")
    assert any(i["id"] == "e2" for i in probs), "engine problem e2 missing"
    s, created = call("POST", "/action/cases", {"insight_id": "e2"})
    assert s == 200 and created["ok"] and created["created"] is True and created["case"]["id"] == "e2"
    cid = created["case"]["id"]
    step(cid, 1, "done", note="定位完成", result="供应商 B 已确认")
    step(cid, 2, "start"); step(cid, 2, "done", note="验证完成", result="阈值已回稳")
    step(cid, 3, "start"); step(cid, 3, "done", note="收尾完成", result="ok")
    s, v = call("POST", f"/action/cases/{cid}/verify", {"outcome": "resolved", "note": "华东订单量回到阈值内，验证通过"})
    assert s == 200 and v["case"]["status"] == "resolved" and "验证通过" in v["case"]["archive"]
    s2, _ = call("POST", f"/action/cases/{cid}/verify", {"outcome": "resolved", "note": "x"})
    assert s2 == 400, "resolved case re-verify should 400"

    # Case2：机会 o1 → 推进到 waiting_verify → verify continue（可复制验证→继续观察）
    s, o = call("POST", "/action/cases", {"insight_id": "o1"})
    assert s == 200 and o["ok"] and o["created"] is False and o["case"]["id"] == "o1"  # 静态 seed 档案幂等
    ocid = "o1"
    # seed o1: seq0/1 done、seq2 in_progress、seq3/4 pending → 全 done
    step(ocid, 2, "done", note="拆解完成", result="新品贡献 62%")
    step(ocid, 3, "start"); step(ocid, 3, "done", note="试点完成", result="2 家通过")
    step(ocid, 4, "start"); step(ocid, 4, "done", note="复制推广完成", result="已扩 3 家")
    s, cont = call("POST", f"/action/cases/{ocid}/verify", {"outcome": "continue", "note": "进入下一轮观察"})
    assert s == 200 and cont["case"]["status"] == "running"

    from app.seed import action_cases_from_static
    o1_baseline = next((c, st) for c, st in action_cases_from_static() if c["id"] == "o1")
    repo.upsert_seed_case(o1_baseline[0], o1_baseline[1])  # 复归 o1 基线（F4：sample 不再代做）
    repo.delete_action_case("e2")  # 自清（sample 不重置 action 档案）
    delete(f"/watch/{watch_id}")   # 清理测试 watch
    post("/datasets/sample")  # 还原数据/事件


def main() -> int:
    run_seed()
    repo = Repository()
    section1_crud(repo)
    section2_builder(repo)
    section3_flow(repo)
    section4_e2e(repo)
    print("action_check OK（第 1–4 节：CRUD/建档引擎/状态机服务/闭环 E2E 全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
