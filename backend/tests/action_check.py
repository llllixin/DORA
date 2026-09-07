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


def main() -> int:
    run_seed()
    section1_crud(Repository())
    print("action_check OK（第 1 节 领域 CRUD + seed 迁移幂等）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
