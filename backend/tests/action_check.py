import os
"""V5 action_check：第 1 节 = 领域/持久化 CRUD（T1）；后续节（闭环 E2E）T5 追加；第 8 节 = 来源分类（action-demo-separation）。

运行：cd backend && python3 -m tests.action_check
前置：PostgreSQL 已 seed + 后端在运行（第 1 节仅需 DB；第 4/7/8 节的 HTTP 断言需后端在线，
离线时该节仅打印跳过——门禁 run_all 内 e2e/agent 段已强制后端在线）。
"""
import sys

from app.repository import Repository
from app.seed import run_seed


def section1_crud(repo: Repository) -> None:
    """V5-T1：seed 迁移幂等 + case/step CRUD 往返。

    断言口径（gate-seed-baseline-idempotency）：只断言**门禁能保证的不变量**——
    ① 结构幂等（5 案 × 5 步、编号对齐、不翻倍）② seed 定义基线（`action_cases_from_static()`）
    ③ 重复 seed **不覆盖**已有档案的进度（含已 `resolved` 案不被倒退）。
    库中已有档案的"当前进度"属**用户状态**（会被用户/演示走查推进），不是门禁不变量。
    """
    from app.seed import action_cases_from_static
    # 测试自持基线：显式重建 5 例（运行时 sample 不会归零 seed 档案，F4）
    for case, steps in action_cases_from_static():
        repo.upsert_seed_case(case, steps)
    ids = ["o1", "o2", "p1", "p2", "p3"]
    # 快照（重建后、任何 run_seed 之前）：重复 seed 必须逐行保留这份进度——
    # pristine 案要保持 pristine，已被用户推进/验证到 resolved 的案（如 p3）要保持 resolved
    def _progress(cid: str):
        detail = repo.get_action_case(cid)
        return (detail["status"],
                [(s["seq"], s["status"], s["note"], s["result"]) for s in detail["steps"]])

    snapshot = {cid: _progress(cid) for cid in ids}

    # 重复 seed 幂等（结构 + 不覆盖进度）：case 恰 5 行、编号对齐、每案 5 步、seq 连续、进度逐行不变
    run_seed()
    run_seed()
    cases = repo.list_action_cases()
    assert sorted(c["id"] for c in cases) == ids, f"seed ids: {sorted(c['id'] for c in cases)}"
    codes = {c["id"]: c["code"] for c in cases}
    assert codes == {"p1": "PRF-0831", "p2": "RTN-0816", "p3": "ORD-1022",
                     "o1": "UPC-0418", "o2": "STO-0607"}, codes
    for cid in ids:
        detail = repo.get_action_case(cid)
        steps = detail["steps"]
        assert len(steps) == 5, f"{cid} step count {len(steps)}"
        assert [s["seq"] for s in steps] == [0, 1, 2, 3, 4], f"{cid} seq order {[s['seq'] for s in steps]}"
        assert _progress(cid) == snapshot[cid], (
            f"F4: run_seed 不得覆盖 {cid} 的已有进度 {snapshot[cid]} → {_progress(cid)}")

    # seed 基线分布断在 **seed 定义** 上（live 行进度属用户状态：`upsert_seed_case` 按规则跳过覆盖
    # 已 resolved 案 → live 行即使在"刚重建"后也不保证是基线，见 design D1/D4）
    for case, steps in action_cases_from_static():
        assert len(steps) == 5, f"{case['id']} seed step count {len(steps)}"
        assert [s["status"] for s in steps[:3]] == ["done", "done", "in_progress"], case["id"]
        assert [s["status"] for s in steps[3:]] == ["pending", "pending"], case["id"]
        assert steps[2]["why"], f"{case['id']} seed current step should carry why"

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
    repo.delete_knowledge_by_source("problem", "flow-test")  # 知识库测试残留自清
    repo.delete_knowledge_by_source("problem", "flow-cont")
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
            os.environ.get('DORA_API_BASE', 'http://localhost:8000/api') + path, data=body, method=method,
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
        req = urllib.request.Request(os.environ.get('DORA_API_BASE', 'http://localhost:8000/api') + path, method='DELETE')
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15):
            pass

    post("/datasets/sample")
    # Case4+1：升级 problem e2 → 真实建档 → 完整执行 → resolved
    created_watch = post("/watch", {"text": "帮我关注华东订单量，如果连续三天下降就提醒我", "frequency": "on_update"})
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
    repo.delete_knowledge_by_source("problem", "e2")  # 知识库 e2 resolved 行自清
    delete(f"/watch/{watch_id}")   # 清理测试 watch
    post("/datasets/sample")  # 还原数据/事件


def section5_lesson(repo: Repository) -> None:
    """迭代 36：resolved 档案 → 经验沉淀（幂等/仅 resolved）。"""
    from app.action import flow

    repo.create_action_case(
        case={"id": "lesson-test", "kind": "problem", "code": "LSN-0001",
              "case_title": "经验测试档案", "tag_cls": "red", "source": "测试"},
        steps=[{"seq": 0, "title": "A", "desc": "d", "evidence": "e", "status": "pending"},
               {"seq": 1, "title": "B", "desc": "d", "evidence": "e", "status": "pending"}],
        status="open")
    flow.start_step(repo, "lesson-test", 0)
    flow.done_step(repo, "lesson-test", 0)
    flow.start_step(repo, "lesson-test", 1)
    flow.done_step(repo, "lesson-test", 1)
    flow.verify(repo, "lesson-test", "resolved", note="阈值回稳，验证通过")
    out = repo.create_case_lesson("lesson-test", "验证通过，供应商 B 成本需季度复核")
    assert out["created"] is True and out["lesson"]["code"] == "LSN-0001"
    assert "验证通过" in out["lesson"]["archive"]
    again = repo.create_case_lesson("lesson-test", "again")
    assert again["created"] is False, "lesson archive must be idempotent"
    lessons = repo.list_case_lessons()
    assert any(l["case_id"] == "lesson-test" for l in lessons)
    assert repo.delete_case_lesson("lesson-test") is True
    assert repo.delete_case_lesson("lesson-test") is False
    repo.delete_knowledge_by_source("problem", "lesson-test")
    repo.delete_knowledge_by_source("lesson", "lesson-test")
    repo.delete_action_case("lesson-test")
    run_seed()  # 还原


def section6_knowledge(repo: Repository) -> None:
    """迭代 38：resolved 与沉淀经验按类型自动入库 + 筛选/stats。"""
    from app.action import flow

    repo.create_action_case(
        case={"id": "knowledge-test", "kind": "opportunity", "code": "KNW-0001",
              "case_title": "知识库测试机会", "tag_cls": "green", "source": "测试"},
        steps=[{"seq": 0, "title": "A", "desc": "d", "evidence": "e", "status": "pending"},
               {"seq": 1, "title": "B", "desc": "d", "evidence": "e", "status": "pending"}],
        status="open")
    flow.start_step(repo, "knowledge-test", 0)
    flow.done_step(repo, "knowledge-test", 0)
    flow.start_step(repo, "knowledge-test", 1)
    flow.done_step(repo, "knowledge-test", 1)
    flow.verify(repo, "knowledge-test", "resolved", note="机会成立，进入复制推广")
    # resolved → knowledge opportunity 行
    opp_rows = repo.list_knowledge("opportunity")
    assert any(e["source_id"] == "knowledge-test" and e["note"] == "机会成立，进入复制推广" for e in opp_rows)
    # 沉淀经验 → lesson 行
    repo.create_case_lesson("knowledge-test", "试点通过，可复制到 3 家门店")
    lesson_rows = repo.list_knowledge("lesson")
    assert any(e["source_id"] == "knowledge-test" and "可复制" in e["note"] for e in lesson_rows)
    # 幂等：重复 resolved 已冻结；lesson 重复 created=False 且不新增行
    dup = repo.create_case_lesson("knowledge-test", "again")
    assert dup["created"] is False
    assert sum(1 for e in repo.list_knowledge("lesson") if e["source_id"] == "knowledge-test") == 1

    # 清理
    repo.delete_knowledge_by_source("opportunity", "knowledge-test")
    repo.delete_knowledge_by_source("lesson", "knowledge-test")
    repo.delete_case_lesson("knowledge-test")
    repo.delete_action_case("knowledge-test")
    run_seed()


def _http_origin_checks() -> None:
    """HTTP 层（action-demo-separation）：`?origin=` 三态 + 非法 400；建档 `claim` 幂等。

    离线（后端未运行）时打印跳过，不阻断：门禁 run_all 内 e2e/agent 段已强制后端在线。
    """
    import json
    import os
    import urllib.error
    import urllib.request

    base = os.environ.get("DORA_API_BASE", "http://localhost:8000/api")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            base + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"} if payload is not None else {})
        try:
            with opener.open(req, timeout=20) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    try:
        status, all_body = _call("GET", "/action/cases")
    except OSError as exc:
        print(f"[origin] HTTP 断言跳过（后端未运行：{exc}）")
        return
    assert status == 200 and all("origin" in c for c in all_body["cases"]), all_body
    _, mine = _call("GET", "/action/cases?origin=mine")
    _, demo = _call("GET", "/action/cases?origin=demo")
    _, alias = _call("GET", "/action/cases?origin=all")
    bad_status, bad_body = _call("GET", "/action/cases?origin=bogus")
    assert bad_status == 400, (bad_status, bad_body)
    assert {c["id"] for c in alias["cases"]} == {c["id"] for c in all_body["cases"]}, "缺省 = all"
    assert all(c["origin"] == "engine" for c in mine["cases"]), mine["cases"]
    assert all(c["origin"] == "demo" for c in demo["cases"]) and demo["cases"], demo["cases"]
    assert len(mine["cases"]) + len(demo["cases"]) == len(all_body["cases"]), "mine ∪ demo = all 且不重叠"
    # claim 幂等：p1（前置已归一为 demo）→ engine；重复同结果；不带 claim 不得退回 demo
    s1, r1 = _call("POST", "/action/cases", {"insight_id": "p1", "claim": True})
    s2, r2 = _call("POST", "/action/cases", {"insight_id": "p1", "claim": True})
    s3, r3 = _call("POST", "/action/cases", {"insight_id": "p1"})
    assert (s1, r1["created"]) == (200, False), (s1, r1)
    assert all(r["case"]["origin"] == "engine" for r in (r1, r2, r3)), (r1, r2, r3)
    assert s2 == 200 and s3 == 200, (s2, s3)
    assert "p1" in {c["id"] for c in _call("GET", "/action/cases?origin=mine")[1]["cases"]}, "认领后应出现在 mine"
    print("[origin] HTTP 200/400 + claim 幂等断言已执行（后端在线）")



def _normalize_demo_origin(repo: Repository) -> None:
    """门禁自持基线（与 §1 重建 5 例同一口径）：把静态演示集的 5 份档案归一为 `demo`。

    用户认领属用户状态，run_all 会把它归一（恢复手法 = 删档案 + 重新 seed，见 tasks 5.4）——
    这样门禁不因"用户点过一次「转为行动档案」"而红/漂移。
    """
    from app.seed import action_cases_from_static

    for case, _steps in action_cases_from_static():
        repo.set_action_case_origin(case["id"], "demo")


def section8_origin(repo: Repository) -> None:
    """action-demo-separation：来源分类（demo/engine）/ 列表过滤 / 认领幂等 / 迁移与 seed 幂等 / 步骤不改来源。

    门禁自持基线（与 §1 同一口径）：5 份种子档案的来源标记属**演示基线**——本节进来先归一为 `demo`，
    退出时同样是 `demo`。用户认领属用户状态，会被 run_all 归一（恢复手法 = 删档案 + 重新 seed，见 tasks 5.4）。
    自清理：自建探针档案全部删除；`main()` 另对全库 `{id: origin}` 做前后快照并断言无残留。
    """
    from app import db as app_db
    from app.action import flow
    from app.seed import action_cases_from_static

    seed_ids = ["o1", "o2", "p1", "p2", "p3"]
    seed_cases = {c["id"]: (c, s) for c, s in action_cases_from_static()}

    # 归一演示基线（可重复：无论上一轮门禁或用户是否认领过）
    _normalize_demo_origin(repo)
    assert {c["id"]: c["origin"] for c in repo.list_action_cases() if c["id"] in seed_ids} == \
        {cid: "demo" for cid in seed_ids}

    # ① 种子档案 = demo；引擎建档（缺省）= engine；非法 origin 拒绝且不写库
    tmp = repo.create_action_case(
        case={"id": "origin-test", "kind": "problem", "code": "PRB-ORIGIN", "case_title": "来源测试"},
        steps=[{"seq": 0, "title": "A", "status": "pending"},
               {"seq": 1, "title": "B", "status": "pending"}],
        status="open",
    )
    assert tmp["origin"] == "engine", tmp["origin"]
    assert repo.get_action_case("origin-test")["origin"] == "engine"
    for bad in ("x", "", "engine "):
        for call in (lambda b=bad: repo.create_action_case({"id": "origin-bad"}, [], origin=b),
                     lambda b=bad: repo.set_action_case_origin("origin-test", b)):
            try:
                call()
                raise AssertionError(f"非法 origin 必须被拒绝：{bad!r}")
            except ValueError:
                pass
    assert repo.get_action_case("origin-bad") is None, "拒绝后不得建行"
    assert repo.get_action_case("origin-test")["origin"] == "engine", "拒绝后不得改值"
    assert repo.claim_action_case("no-such-case") is False, "缺案认领 = False（幂等，不抛错）"



    # ② 过滤三态：all ⊇ mine ∪ demo（互斥且各自 origin 全对）；非法值抛 ValueError
    all_cases = repo.list_action_cases()
    mine = repo.list_action_cases("mine")
    demo = repo.list_action_cases("demo")
    assert {c["id"] for c in all_cases} == {c["id"] for c in mine} | {c["id"] for c in demo}
    assert not ({c["id"] for c in mine} & {c["id"] for c in demo}), "mine/demo 必须互斥"
    assert all(c["origin"] == "engine" for c in mine), mine
    assert all(c["origin"] == "demo" for c in demo) and demo, demo
    assert "origin-test" in {c["id"] for c in mine} and set(seed_ids) <= {c["id"] for c in demo}
    assert {c["id"] for c in repo.list_action_cases("all")} == {c["id"] for c in all_cases}, "all = 缺省"
    assert {c["id"] for c in repo.list_action_cases(None)} == {c["id"] for c in all_cases}, "None = 缺省"
    for bogus in ("bogus", "unknown", "*", "engine+1"):
        try:
            repo.list_action_cases(bogus)
            raise AssertionError(f"非法过滤值必须抛 ValueError：{bogus!r}")
        except ValueError:
            pass
    # 归一而非兜底：大小写/空白变体 == 同义值（不算静默兜底，未知值仍拒）
    assert {c["id"] for c in repo.list_action_cases("MINE")} == {c["id"] for c in mine}
    assert {c["id"] for c in repo.list_action_cases(" demo ")} == {c["id"] for c in demo}

    # ③ 认领：只对演示档案生效且幂等；不带认领语义的路径不改来源
    assert repo.claim_action_case("p1") is True and repo.get_action_case("p1")["origin"] == "engine"
    assert repo.claim_action_case("p1") is False, "重复认领必须幂等（返回 False 而非重写）"
    assert repo.get_action_case("p1")["origin"] == "engine"
    assert repo.claim_action_case("origin-test") is False, "非演示档案不得被认领"
    assert repo.get_action_case("origin-test")["origin"] == "engine"
    assert "p1" in {c["id"] for c in repo.list_action_cases("mine")}, "认领后应进「我的」"
    assert "p1" not in {c["id"] for c in repo.list_action_cases("demo")}, "认领后应离开「演示」"

    # ⑤ 迁移 / seed 幂等：已认领档案不得被 seed 或 init_db 倒退成演示，步骤数据仍不覆盖
    p1_progress = [(s["seq"], s["status"]) for s in repo.get_action_case("p1")["steps"]]
    repo.upsert_seed_case(*seed_cases["p1"])
    app_db.init_db()
    assert repo.get_action_case("p1")["origin"] == "engine", "已认领档案不得被 seed/迁移倒退"
    assert [(s["seq"], s["status"]) for s in repo.get_action_case("p1")["steps"]] == p1_progress, \
        "seed 迁移不得改写步骤进度"
    assert repo.get_action_case("p2")["origin"] == "demo", "未认领的演示档案保持 demo"

    # ④ 步骤动作 / 验证全链路不写 origin（自建探针档案上走完 start→done→verify）
    flow.start_step(repo, "origin-test", 0)
    flow.done_step(repo, "origin-test", 0, note="来源回归", result="ok")
    assert repo.get_action_case("origin-test")["origin"] == "engine", "步骤动作不得改来源标记"
    flow.start_step(repo, "origin-test", 1)
    flow.done_step(repo, "origin-test", 1, note="来源回归", result="ok")
    assert repo.get_action_case("origin-test")["status"] == "waiting_verify"
    assert flow.verify(repo, "origin-test", "resolved", note="来源回归归档")["origin"] == "engine", \
        "验证归档不得改来源标记"

    # HTTP 层（后端在线时；此处会认领 p1，末尾统一归一）
    _http_origin_checks()

    # 自清理：探针档案删除 + 演示基线归一（main() 会再断一次全库快照）
    repo.delete_action_case("origin-test")
    assert repo.get_action_case("origin-test") is None
    _normalize_demo_origin(repo)
    assert {c["id"]: c["origin"] for c in repo.list_action_cases() if c["id"] in seed_ids} == \
        {cid: "demo" for cid in seed_ids}, "演示基线未归一"
    print("[origin] 来源分类/过滤/认领幂等/迁移幂等/步骤不改来源 全绿 + 演示基线已归一")



def _purge_orphans(repo: Repository) -> dict[str, int]:
    """生命周期不变式自愈（A1）：清理非 resolved / 不存在档案残留的 case_lesson 与 knowledge 孤儿行。"""
    removed = {"case_lesson": 0, "knowledge": 0}
    for lesson in repo.list_case_lessons():
        case = repo.get_action_case(lesson["case_id"])
        if case is None or case["status"] != "resolved":
            if repo.delete_case_lesson(lesson["case_id"]):
                removed["case_lesson"] += 1
    for entry in repo.list_knowledge():
        case = repo.get_action_case(entry["source_id"])
        if case is None or case["status"] != "resolved":
            if repo.delete_knowledge_by_source(entry["entry_type"], entry["source_id"]):
                removed["knowledge"] += 1
    return removed


def assert_no_orphans(repo: Repository) -> None:
    """不变式断言：case_lesson / knowledge 行只允许归属 resolved 档案（A1）。"""
    for lesson in repo.list_case_lessons():
        case = repo.get_action_case(lesson["case_id"])
        assert case is not None and case["status"] == "resolved", f"orphan lesson for {lesson['case_id']}"
    for entry in repo.list_knowledge():
        case = repo.get_action_case(entry["source_id"])
        assert case is not None and case["status"] == "resolved", \
            f"orphan knowledge {entry['entry_type']}/{entry['source_id']}"


def _http_expert_checks() -> None:
    """HTTP 层：200 设置/重放 + 400（空名/超限/缺步）+ 404（缺案）+ 422（名单非法）。

    离线（后端未运行）时打印跳过，不阻断：门禁 run_all 内 e2e/agent 段已强制后端在线。
    """
    import json
    import os
    import urllib.error
    import urllib.request

    base = os.environ.get("DORA_API_BASE", "http://localhost:8000/api")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _post(path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(base + path, method="POST",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=8) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    try:
        status, body = _post("/action/cases/exp-test/steps/1/experts", {"experts": ["经营分析专家"]})
    except OSError as exc:
        print(f"[experts] HTTP 断言跳过（后端未运行：{exc}）")
        return
    assert status == 200 and body["ok"] is True, (status, body)
    assert [s["experts"] for s in body["case"]["steps"]][1] == ["经营分析专家"], body["case"]["steps"][1]
    # 重放同值幂等（不追加、不报错）
    status, body = _post("/action/cases/exp-test/steps/1/experts", {"experts": ["经营分析专家"]})
    assert status == 200 and [s["experts"] for s in body["case"]["steps"]][1] == ["经营分析专家"]
    # 4xx：空名 / 超限 / 缺步
    assert _post("/action/cases/exp-test/steps/1/experts", {"experts": [""]})[0] == 400
    assert _post("/action/cases/exp-test/steps/1/experts", {"experts": [f"专家{i}" for i in range(9)]})[0] == 400
    assert _post("/action/cases/exp-test/steps/42/experts", {"experts": ["财务专家"]})[0] == 400
    # 4xx：名单非字符串列表（pydantic 校验）
    assert _post("/action/cases/exp-test/steps/1/experts", {"experts": "财务专家"})[0] in (400, 422)
    # 拒绝后库中值不变（仍为重放后的名单）
    kept = _post("/action/cases/exp-test/steps/1/experts", {"experts": ["经营分析专家"]})[1]
    assert [s["experts"] for s in kept["case"]["steps"]][1] == ["经营分析专家"], "拒绝请求后名单不得被改写"
    # 404：缺案
    assert _post("/action/cases/no-such-case/steps/0/experts", {"experts": ["财务专家"]})[0] == 404
    # 空列表 = 清除
    status, body = _post("/action/cases/exp-test/steps/1/experts", {"experts": []})
    assert status == 200 and [s["experts"] for s in body["case"]["steps"]][1] == [], body["case"]["steps"][1]
    print("[experts] HTTP 200/400/404/422 断言已执行（后端在线）")


def section7_step_experts(repo: Repository) -> None:
    """action-loop-timeline：每步负责专家（整体设置幂等 / 去重 / 上限 / 冻结 / 404）。"""
    from app.action import flow

    # 迁移前历史步行缺省空名单（不伪造专家、不报错）
    for cid in ("p1", "o1"):
        detail = repo.get_action_case(cid)
        assert all(s["experts"] == [] for s in detail["steps"]), f"{cid} seeded steps should have empty experts"

    repo.create_action_case(
        case={"id": "exp-test", "kind": "problem", "code": "TST-0911",
              "case_title": "专家测试", "tag_cls": "red", "source": "测试"},
        steps=[{"seq": 0, "title": "A", "desc": "d", "evidence": "e", "status": "pending"},
               {"seq": 1, "title": "B", "desc": "d2", "evidence": "e2", "status": "pending"}],
        status="open",
    )
    assert repo.get_action_case("exp-test")["steps"][0]["experts"] == [], "新建步骤应为空名单"

    # repo 层：去重保序 + 不牵连其它步骤 + 不存在 seq/case 返回 None（幂等）
    step = repo.set_action_step_experts("exp-test", 1, ["财务专家", "财务专家", "销售专家"])
    assert step is not None and step["experts"] == ["财务专家", "销售专家"], step and step.get("experts")
    again = repo.get_action_case("exp-test")
    assert again["steps"][1]["experts"] == ["财务专家", "销售专家"], "往返一致"
    assert again["steps"][0]["experts"] == [], "设置某步不得牵连其它步骤"
    assert repo.set_action_step_experts("exp-test", 9, ["x"]) is None
    assert repo.set_action_step_experts("no-such-case", 0, ["x"]) is None

    # flow 层：幂等重放不追加 → 整体替换（移除靠缺席）→ 空白裁剪 → 空列表清除
    c1 = flow.set_step_experts(repo, "exp-test", 1, ["财务专家", "销售专家"])
    assert c1["steps"][1]["experts"] == ["财务专家", "销售专家"], "重放不得追加"
    c2 = flow.set_step_experts(repo, "exp-test", 0, ["经营分析专家", " 供应链专家 "])
    assert c2["steps"][0]["experts"] == ["经营分析专家", "供应链专家"], c2["steps"][0]["experts"]
    assert c2["steps"][1]["experts"] == ["财务专家", "销售专家"], "设置 seq=0 不得动 seq=1"
    assert flow.set_step_experts(repo, "exp-test", 0, [])["steps"][0]["experts"] == [], "空列表=清除"

    # 结构性校验：空名 / 超 8 → 拒绝且不写库；恰好 8 个接受
    for bad in ([""], ["财务专家", "   "], [f"专家{i}" for i in range(9)]):
        try:
            flow.set_step_experts(repo, "exp-test", 1, bad)
            raise AssertionError(f"illegal experts must be rejected: {bad}")
        except flow.ActionFlowError:
            pass
    assert repo.get_action_case("exp-test")["steps"][1]["experts"] == ["财务专家", "销售专家"], "拒绝后不得写库"
    eight = [f"专家{i}" for i in range(8)]
    assert flow.set_step_experts(repo, "exp-test", 1, eight)["steps"][1]["experts"] == eight, "恰好 8 个应接受"

    # 不存在 seq / case → 拒绝语义（router 分别映射 400 / 404）
    for bad_args in (("exp-test", 42), ("no-such-case", 0)):
        try:
            flow.set_step_experts(repo, bad_args[0], bad_args[1], ["财务专家"])
            raise AssertionError(f"missing step/case must be rejected: {bad_args}")
        except flow.ActionFlowError:
            pass

    # HTTP 层 200/400/404/422（后端在线时；必须在 resolved 之前，冻结后一律 4xx）
    _http_expert_checks()

    # resolved 冻结：设置专家 4xx 且不写库
    flow.start_step(repo, "exp-test", 0)
    flow.done_step(repo, "exp-test", 0)
    flow.start_step(repo, "exp-test", 1)
    flow.done_step(repo, "exp-test", 1)
    assert flow.verify(repo, "exp-test", "resolved", note="专家测试归档")["status"] == "resolved"
    before = repo.get_action_case("exp-test")["steps"][1]["experts"]
    try:
        flow.set_step_experts(repo, "exp-test", 1, ["财务专家"])
        raise AssertionError("resolved case must freeze expert assignment")
    except flow.ActionFlowError:
        pass
    assert repo.get_action_case("exp-test")["steps"][1]["experts"] == before, "冻结后不得写库"

    repo.delete_action_case("exp-test")
    repo.delete_knowledge_by_source("problem", "exp-test")
    print("[experts] 每步负责专家：往返/去重/幂等/整体替换/上限/冻结/404 全绿")


def main() -> int:
    run_seed()
    repo = Repository()
    removed = _purge_orphans(repo)
    if removed["case_lesson"] or removed["knowledge"]:
        print(f"[lifecycle] self-heal removed orphan rows: knowledge={removed['knowledge']}, case_lesson={removed['case_lesson']}")
    # 污染守卫（action-demo-separation）：演示基线先归一 + 清掉上一轮可能的探针残留
    # （门禁自持口径，见 _normalize_demo_origin），跑完不得残留探针档案、也不得改动任何档案的来源标记
    _normalize_demo_origin(repo)
    repo.delete_action_case("origin-test")
    origin_before = {c["id"]: c["origin"] for c in repo.list_action_cases()}
    section1_crud(repo)
    section2_builder(repo)
    section3_flow(repo)
    section4_e2e(repo)
    section5_lesson(repo)
    section6_knowledge(repo)
    section7_step_experts(repo)
    section8_origin(repo)
    origin_after = {c["id"]: c["origin"] for c in repo.list_action_cases()}
    leftover = {k: (origin_before.get(k), v) for k, v in origin_after.items() if origin_before.get(k) != v}
    assert not leftover, f"action_check 必须自清理来源标记：残留 {leftover}"
    assert_no_orphans(repo)
    print("action_check OK（第 1–8 节 + 生命周期不变式：CRUD/建档/状态机/闭环 E2E/经验沉淀/知识库/步骤负责专家/来源分类 全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
