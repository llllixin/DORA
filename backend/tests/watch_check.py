"""V4 watch_check：第 1 节 = 领域/持久化 CRUD（T1）；第 2 节 = 升级路径 E2E（T5 追加）。

运行：cd backend && python3 -m tests.watch_check
前置：PostgreSQL 已 seed（本地 docker compose up -d 后 python -m app.seed）。
"""
import sys

from app.repository import Repository
from app.seed import run_seed

INTENT = {
    "metric_key": "east_orders",
    "dimension": "华东",
    "condition": {"type": "streak_below", "days": 3, "ref": None},
    "frequency": "on_update",
}


def section1_crud(repo: Repository) -> None:
    """V4-T1：watch_target / watch_event 持久化往返。"""
    # 创建 → 列表 → 单查
    created = repo.create_watch_target(
        "帮我关注华东销售额，如果连续三天下降就提醒我", INTENT,
        status="watching", frequency="on_update",
    )
    tid = created["id"]
    assert tid.startswith("w-"), f"watch id prefix: {tid}"
    targets = repo.list_watch_targets()
    assert any(t["id"] == tid and t["status"] == "watching" for t in targets), "list must contain created target"
    got = repo.get_watch_target(tid)
    assert got is not None and got["intent"]["metric_key"] == "east_orders"
    assert got["frequency"] == "on_update" and got["created_at"], "structured fields kept"

    # 枚举校验早暴露
    try:
        repo.create_watch_target("bad status", {}, status="nope")
        raise AssertionError("invalid status should raise")
    except ValueError:
        pass
    try:
        repo.add_watch_event(tid, "boom", "x")
        raise AssertionError("invalid event kind should raise")
    except ValueError:
        pass

    # 暂停后读回
    updated = repo.set_watch_status(tid, "paused")
    assert updated is not None and updated["status"] == "paused"
    assert repo.get_watch_target(tid)["status"] == "paused", "pause persisted"

    # 事件追加（顺序）+ 目标 last_event_at 刷新
    e1 = repo.add_watch_event(tid, "change", "华东订单量开始回落", {"prev": 100.0, "cur": 98.2, "metric": "east_orders", "dimension": "华东"})
    e2 = repo.add_watch_event(tid, "escalate", "跌破升级条件，建议关注", {"prev": -2.1, "cur": -3.4, "metric": "east_orders", "dimension": "华东"})
    events = repo.list_watch_events(tid)
    assert [ev["kind"] for ev in events] == ["change", "escalate"], f"event order: {events}"
    assert e1["id"] and e2["id"] and e2["id"] > e1["id"]
    assert repo.get_watch_target(tid)["last_event_at"], "last_event_at refreshed"

    # 未知 id 语义
    assert repo.get_watch_target("w-does-not-exist") is None
    assert repo.list_watch_events("w-does-not-exist") == []
    assert repo.set_watch_status("w-does-not-exist", "paused") is None
    try:
        repo.add_watch_event("w-does-not-exist", "change", "x")
        raise AssertionError("event on missing target should raise")
    except ValueError:
        pass

    # 删除级联 + 幂等
    assert repo.delete_watch_target(tid) is True
    assert repo.get_watch_target(tid) is None, "target gone after delete"
    assert repo.list_watch_events(tid) == [], "events cascade-deleted"
    assert repo.delete_watch_target(tid) is False, "second delete is no-op"

    # count_rows 映射可用
    assert repo.count_rows("watch_target") >= 0
    assert repo.count_rows("watch_event") >= 0


def main() -> int:
    run_seed()  # 建表 + 出厂重置（watch 表无种子，恒空起步）
    section1_crud(Repository())
    print("watch_check OK（第 1 节 领域 CRUD 全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
