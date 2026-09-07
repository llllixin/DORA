"""V4 watch_check：第 1 节 = 领域/持久化 CRUD（T1）；第 2 节 = 委托解析（T2）；第 3 节 = 升级路径 E2E（T5 追加）。

运行：cd backend && python3 -m tests.watch_check
前置：PostgreSQL 已 seed（本地 docker compose up -d 后 python -m app.seed）。
"""
import sys

from app.repository import Repository
from app.seed import run_seed
from app.watch.parser import parse_watch_text

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


def section2_parser() -> None:
    """V4-T2：委托语句 → 结构化 intent（词典 + 显式拒绝 + 建议默认）。"""
    # 支持句式：demo 句（east_orders/华东/连续 3 天下降）
    r = parse_watch_text("帮我关注华东销售额，如果连续三天下降就提醒我")
    assert r["ok"], r
    i = r["intent"]
    assert i["metric_key"] == "east_orders" and i["dimension"] == "华东"
    assert i["condition"] == {"type": "streak_below", "days": 3, "ref": None}
    assert i["label"] == "华东销售额" and i["frequency"] is None
    assert i["condition_defaulted"] is False

    # 值跌破 + 频率词
    r = parse_watch_text("关注利润率，跌破 18% 就提醒我，每天 09:00 检查")
    assert r["ok"]
    i = r["intent"]
    assert i["metric_key"] == "margin" and i["dimension"] == "全国"
    assert i["condition"] == {"type": "below", "ref": 18.0, "ref_is_pct": True}
    assert i["frequency"] == "daily 09:00" and i["condition_defaulted"] is False

    # 中文数字天数 + 建议默认标记
    r = parse_watch_text("帮我关注新品增长，连续两天上涨就提醒我")
    assert r["ok"] and r["intent"]["metric_key"] == "new_sku"
    assert r["intent"]["condition"] == {"type": "streak_above", "days": 2, "ref": None}
    r = parse_watch_text("关注退货率")
    assert r["ok"] and r["intent"]["dimension"] == ""
    assert r["intent"]["condition_defaulted"] is True, "缺条件应给建议默认并标记"

    # 拒绝句式：unknown 指标
    r = parse_watch_text("关注库存周转，连续 3 天下跌就提醒我")
    assert r["ok"] is False and r["intent"] is None
    assert r["unsupported"] and "库存周转" in r["unsupported"][0]["token"]

    # 前端建议 chips 映射：受支持的 5 个 ok=true，库存周转显式拒绝
    chips = ["利润率", "华东销售", "新品增长", "退货率", "大额订单", "库存周转"]
    ok_count = sum(1 for c in chips if parse_watch_text(f"帮我关注{c}")["ok"])
    assert ok_count == 5, f"supported chips should be 5, got {ok_count}"
    assert parse_watch_text("帮我关注库存周转")["ok"] is False


def main() -> int:
    run_seed()  # 建表 + 出厂重置（watch 表无种子，恒空起步）
    section1_crud(Repository())
    section2_parser()
    print("watch_check OK（第 1 节 领域 CRUD + 第 2 节 解析 全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
