"""V4 watch_check：第 1 节 = 领域/持久化 CRUD（T1）；第 2 节 = 委托解析（T2）；第 3 节 = 评估器（T3）；第 4 节 = Case 3/4 升级 E2E（T5，HTTP）；第 5 节 = 卡片走向摘要 trend + 引擎判定引用 engineInsightId（watch-goal-workbench，直连 repo + _watch_card）；第 6 节 = 升级即移交（watch-escalate-handoff：终态/凭据约束/恢复+去重仍移交/重置归位/backfill 幂等/卡片三态/置态限制/check 守卫，直连 repo + HTTP）。

运行：cd backend && python3 -m tests.watch_check
前置：PostgreSQL 已 seed + 后端在运行（本地 docker compose up -d、uvicorn :8000）。
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
        "帮我关注华东订单量，如果连续三天下降就提醒我", INTENT,
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
    r = parse_watch_text("帮我关注华东订单量，如果连续三天下降就提醒我")
    assert r["ok"], r
    i = r["intent"]
    assert i["metric_key"] == "east_orders" and i["dimension"] == "华东"
    assert i["condition"] == {"type": "streak_below", "days": 3, "ref": None}
    assert i["label"] == "华东订单量" and i["frequency"] is None
    assert i["condition_defaulted"] is False

    # 值跌破 + 频率词
    r = parse_watch_text("关注利润率，跌破 18% 就提醒我，每天 09:00 检查")
    assert r["ok"]
    i = r["intent"]
    assert i["metric_key"] == "margin" and i["dimension"] == "全国"
    assert i["condition"] == {"type": "below", "ref": 18.0, "ref_is_pct": True}
    assert i["frequency"] == "daily 09:00" and i["condition_defaulted"] is False

    # 中文数字天数 + 建议默认标记
    r = parse_watch_text("帮我关注新品销量，连续两天上涨就提醒我")
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
    chips = ["利润率", "华东订单量", "新品销量", "退货率", "高客单门店占比", "库存周转"]
    ok_count = sum(1 for c in chips if parse_watch_text(f"帮我关注{c}")["ok"])
    assert ok_count == 5, f"supported chips should be 5, got {ok_count}"
    assert parse_watch_text("帮我关注库存周转")["ok"] is False


def section3_evaluator(repo: Repository) -> None:
    """V4-T3：条件求值（命中/升级/未命中/去重）+ 周期到期判断。"""
    from datetime import datetime, timezone
    from app.engine.engine import run_engine
    from app.watch.evaluator import evaluate_all
    from app.watch.scheduler import _is_due

    def put(key, dimension, values, unit=""):
        repo.replace_series([key], [
            {"metric_key": key, "label": f"T{i}", "dimension": dimension, "value": float(v), "unit": unit}
            for i, v in enumerate(values)
        ])

    # 升级场景：east_orders 连续下跌并跌破引擎升级阈值 → escalate 引用 e2
    run_seed()
    put("east_orders", "华东", [105.0, 103.0, 100.0, 97.0, 93.0])
    t1 = repo.create_watch_target(
        "升级场景", {"metric_key": "east_orders", "dimension": "华东", "label": "华东订单量",
                     "condition": {"type": "streak_below", "days": 3, "ref": None}},
        frequency="on_update")
    stats = evaluate_all(repo)
    evs = repo.list_watch_events(t1["id"])
    assert len(evs) == 1 and evs[0]["kind"] == "escalate", f"expect escalate event, got {evs}"
    assert evs[0]["values"]["engine_insight"] == "e2", "escalate must reference engine insight e2"
    assert stats["escalate"] >= 1
    assert repo.get_watch_target(t1["id"])["last_checked_at"], "last_checked_at updated"

    # watch-escalate-handoff：升级即移交 → 终态不再被评估（事件与最近检查时刻都冻结）
    assert repo.get_watch_target(t1["id"])["status"] == "escalated", "escalate must hand off to terminal"
    frozen_at = repo.get_watch_target(t1["id"])["last_checked_at"]
    stats2 = evaluate_all(repo)
    assert repo.list_watch_events(t1["id"]) == evs, "terminal target must NOT be re-evaluated"
    assert repo.get_watch_target(t1["id"])["last_checked_at"] == frozen_at, "terminal last_checked_at frozen"
    repo.delete_watch_target(t1["id"])

    # 去重仍是评估器契约（用非升级指标 new_sku 走 change 去重路径：升级路径已终态，去重不再适用）
    run_seed()
    put("new_sku", "全区域", [100.0, 98.0, 95.0, 92.0])
    t3 = repo.create_watch_target(
        "去重", {"metric_key": "new_sku", "dimension": "全区域", "label": "新品销量",
                 "condition": {"type": "streak_below", "days": 3, "ref": None}},
        frequency="on_update")
    evaluate_all(repo)
    evs_ch = repo.list_watch_events(t3["id"])
    assert len(evs_ch) == 1 and evs_ch[0]["kind"] == "change", f"expect change event: {evs_ch}"
    assert repo.get_watch_target(t3["id"])["status"] == "watching", "change must stay in-hand"
    stats_ch = evaluate_all(repo)
    assert repo.list_watch_events(t3["id"]) == evs_ch, "duplicate event must be skipped"
    assert stats_ch["skipped"] >= 1
    repo.delete_watch_target(t3["id"])

    # 未命中：margin 高值未跌破 → miss、无事件
    run_seed()
    put("margin", "全国", [19.6, 19.4, 19.3], "%")
    t2 = repo.create_watch_target(
        "未命中", {"metric_key": "margin", "dimension": "全国", "label": "利润率",
                   "condition": {"type": "below", "ref": 18.0, "ref_is_pct": True}},
        frequency="on_update")
    stats = evaluate_all(repo)
    assert stats["miss"] >= 1 and repo.list_watch_events(t2["id"]) == []
    repo.delete_watch_target(t2["id"])

    # 周期到期判断（纯函数注入 now）
    utc = timezone.utc
    d_target = {"id": "t-d", "status": "watching", "frequency": "daily 09:00", "last_checked_at": ""}
    w_target = {"id": "t-w", "status": "watching", "frequency": "weekly", "last_checked_at": ""}
    assert _is_due(d_target, datetime(2026, 9, 7, 8, 59, tzinfo=utc)) is False, "before 09:00 not due"
    assert _is_due(d_target, datetime(2026, 9, 7, 9, 3, tzinfo=utc)) is True, "after 09:00 due"
    d_target["last_checked_at"] = "2026-09-07T09:10:00+00:00"
    assert _is_due(d_target, datetime(2026, 9, 7, 10, 0, tzinfo=utc)) is False, "already checked today"
    assert _is_due(w_target, datetime(2026, 9, 7, 9, 0, tzinfo=utc)) is True, "monday due"  # 2026-09-07 = Mon
    w_target["last_checked_at"] = "2026-09-07T09:05:00+00:00"
    assert _is_due(w_target, datetime(2026, 9, 8, 9, 0, tzinfo=utc)) is False, "same week not due again"
    assert _is_due(w_target, datetime(2026, 9, 14, 9, 0, tzinfo=utc)) is True, "next monday due"
    paused = {"id": "t-p", "status": "paused", "frequency": "daily 09:00", "last_checked_at": ""}
    assert _is_due(paused, datetime(2026, 9, 7, 10, 0, tzinfo=utc)) is False, "paused not due"

    run_seed()  # 恢复出厂（清理 crafted 序列与事件）


def section4_e2e(repo: Repository) -> None:
    """V4-T5：Case 3/4 委托升级路径端到端（HTTP + 上传即时评估）。

    前置：后端在运行（run_all 已有此前置，同 e2e_api_check）。
    Case 3：变化 → watch（change 事件）；Case 4：继续恶化 → 引擎 e2 → escalate 事件回脉搏。
    """
    import os
    import urllib.request
    from tests.e2e_api_check import east_breach_csv, get, post, post_file

    BASE = os.environ.get("DORA_API_BASE", "http://localhost:8000/api")

    def delete(path: str):
        req = urllib.request.Request(BASE + path, method="DELETE")
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10):
            pass

    post("/datasets/sample")
    created = post("/watch", {"text": "帮我关注华东订单量，如果连续三天下降就提醒我", "frequency": "on_update"})
    assert created.get("ok") and created["target"]["status"] == "watching"
    tid = created["target"]["id"]

    # watch-delegate-flow：创建卡片即刻回显解析结果 + 最近检查时刻 + 最近命中（change）
    ccard = created["target"]
    assert ccard["intent"]["metric_key"] == "east_orders", f"create card intent expected, got {ccard.get('intent')}"
    assert ccard["lastCheckedAt"], f"create card lastCheckedAt expected non-empty, got {ccard!r}"
    assert ccard["lastEvent"] and ccard["lastEvent"]["kind"] == "change", \
        f"create card change event expected, got {ccard.get('lastEvent')}"
    assert ccard["lastEvent"]["summary"], "create card event summary expected non-empty"

    # Case 3：创建即评估 → 变化命中（watch 事件）
    det = get(f"/watch/{tid}")
    kinds = [e["kind"] for e in det["events"]]
    assert "change" in kinds, f"Case 3: change event expected, got {kinds}"

    # Case 4：上传跌破升级阈值 → 引擎 e2 且委托 escalate 引用 e2
    up = post_file("/datasets", "east_breach_v4.csv", east_breach_csv())
    assert up.get("ok"), "breach upload failed"
    det2 = get(f"/watch/{tid}")
    escalates = [e for e in det2["events"] if e["kind"] == "escalate"]
    assert escalates and escalates[-1]["values"]["engine_insight"] == "e2", \
        f"Case 4: escalate referencing e2 expected, got {det2['events']}"
    probs = get("/insights?type=problem")
    assert any(i["id"] == "e2" for i in probs), "engine e2 problem missing after breach"
    cards = get("/watch")
    card = next(c for c in cards if c["id"] == tid)
    assert card["value"] == "已升级" and card["color"] == "red", f"card should be escalated, got {card}"

    # watch-delegate-flow：升级卡片回显 escalate 事件且文案引用引擎判定（run_engine 的 trigger）
    ins = get("/insights/e2")
    assert card["intent"]["metric_key"] == "east_orders" and card["intent"]["dimension"] == "华东", \
        f"escalate card intent expected, got {card.get('intent')}"
    assert card["lastCheckedAt"], "escalate card lastCheckedAt expected non-empty"
    ev = card["lastEvent"]
    assert ev and ev["kind"] == "escalate", f"escalate event expected, got {ev}"
    assert ev["summary"] == f"已升级：{ins['trigger']}", \
        f"event summary must quote engine judgement, got {ev['summary']!r} vs {ins['trigger']!r}"
    assert ev["triggeredAt"], "lastEvent.triggeredAt expected non-empty"

    # watch-delegate-flow：未命中委托不伪造事件（lastEvent is None），但仍记录最近检查时刻
    miss = post("/watch", {"text": "帮我关注华东订单量，如果超过 999999 就提醒我", "frequency": "on_update"})
    miss_id = miss["target"]["id"]
    mcard = next(c for c in get("/watch") if c["id"] == miss_id)
    assert mcard["lastEvent"] is None, f"miss target must keep lastEvent null, got {mcard['lastEvent']}"
    assert mcard["lastCheckedAt"], "miss target still evaluated (lastCheckedAt set)"

    delete(f"/watch/{miss_id}")
    delete(f"/watch/{tid}")
    post("/datasets/sample")  # 还原出厂


def section5_trend(repo: Repository) -> None:
    """watch-goal-workbench：卡片走向摘要（`trend`）与引擎判定引用（`engineInsightId`）。

    四组断言：① `trend` 契约 + 与评估器同源同值；② 同源场景（走向说跌 == 评估器命中）；
    ③ 无序列不编造；④ `engineInsightId` 三态（无命中 / change / escalate）。
    """
    from app.routers import _watch_card
    from app.watch.evaluator import _decline_run, _rise_run, chrono_points, evaluate_all, evaluate_one
    from app.watch.trend import build_trend

    key, dim = "east_orders", "华东"

    def put(values: list[float], unit: str = "") -> None:
        repo.replace_series([key], [
            {"metric_key": key, "label": f"T{i}", "dimension": dim, "value": float(v), "unit": unit}
            for i, v in enumerate(values)
        ])

    def make(text: str, metric_key: str, dimension: str, cond: dict) -> str:
        return repo.create_watch_target(
            text, {"metric_key": metric_key, "dimension": dimension, "label": "华东订单量", "condition": cond},
            frequency="on_update",
        )["id"]

    def card_of(tid: str) -> dict:
        return _watch_card(repo, repo.get_watch_target(tid))

    # ① 契约 + 同源同值（points 必须是 chrono_points 时间线的末尾窗口）
    run_seed()
    rows = repo.get_series(key)
    timeline = chrono_points(rows, dim)
    values = [v for _, v in timeline]
    t_contract = make("走向契约", key, dim, {"type": "streak_below", "days": 3, "ref": None})
    tr = card_of(t_contract)["trend"]
    assert tr is not None, "seeded east_orders/华东 must expose a trend"
    assert tr["metricKey"] == key and tr["dimension"] == dim, tr
    assert tr["unit"] == (rows[0].get("unit") or ""), f"unit must come from the same series: {tr['unit']!r}"
    assert 0 < len(tr["points"]) <= 12, f"display window must be <= 12 points: {len(tr['points'])}"
    assert [(p["label"], p["value"]) for p in tr["points"]] == timeline[-len(tr["points"]):], \
        "points must be the TAIL of the chrono_points timeline (evaluator's own entry)"
    # 同源校验：与只读工具读到的序列行逐点一致（不许有第二条判定链/时间窗口径）
    tool_rows = repo.list_metric_series(key, dim, 200)
    assert [(p["label"], p["value"]) for p in tr["points"]] == \
        [(r["label"], r["value"]) for r in tool_rows][-len(tr["points"]):], \
        "trend points must match repository series rows for the same dimension"
    down, up = _decline_run(values), _rise_run(values)
    assert tr["direction"] == ("down" if down > 0 else "up" if up > 0 else "flat"), tr["direction"]
    assert tr["runDays"] == (down if down > 0 else up), f"runDays must be the FULL-series run: {tr}"
    first_v, last_v = tr["points"][0]["value"], tr["points"][-1]["value"]
    assert tr["changePct"] == round((last_v - first_v) / abs(first_v) * 100, 1), \
        f"changePct must be window first→last: {tr['changePct']}"
    assert tr["basis"], "basis must be non-empty（自陈窗口/范围/口径）"
    repo.delete_watch_target(t_contract)

    # ② 同源场景：末三点单调下降 + streak_below(3) → 走向说跌，评估器必须同时命中
    put([105.0, 103.0, 100.0, 97.0, 93.0], "%")
    t_same = make("同源", key, dim, {"type": "streak_below", "days": 3, "ref": None})
    card_same = card_of(t_same)
    assert card_same["trend"]["direction"] == "down" and card_same["trend"]["runDays"] >= 3, card_same["trend"]
    out = evaluate_one(repo, repo.get_watch_target(t_same))
    assert out["hit"] is True, f"evaluator must hit when trend says down: {out}"

    # ④-b escalate 态：engineInsightId 非空且 == 事件 values.engine_insight
    card_esc = card_of(t_same)
    evs = repo.list_watch_events(t_same)
    assert card_esc["lastEvent"]["kind"] == "escalate", f"crafted breach must escalate: {evs}"
    assert card_esc["engineInsightId"] == evs[-1]["values"]["engine_insight"] == "e2", \
        f"engineInsightId must quote the escalate event: {card_esc['engineInsightId']}"
    repo.delete_watch_target(t_same)

    # ④-c change 态（引擎未判定升级）→ null
    run_seed()
    t_change = make("变化态", key, dim, {"type": "streak_below", "days": 3, "ref": None})
    evaluate_all(repo)
    card_ch = card_of(t_change)
    assert card_ch["lastEvent"]["kind"] == "change", f"seed state must stay at change: {card_ch['lastEvent']}"
    assert card_ch["engineInsightId"] is None, \
        f"engineInsightId must stay null unless escalate: {card_ch['engineInsightId']}"
    assert card_ch["trend"] is not None, "change card still exposes trend（走向与判定正交）"
    repo.delete_watch_target(t_change)

    # ④-a 无命中 → null（trend 仍在：无事件不等于无数据）
    run_seed()
    t_miss = make("无命中", "margin", "全国", {"type": "below", "ref": 1.0})
    evaluate_all(repo)
    card_miss = card_of(t_miss)
    assert repo.list_watch_events(t_miss) == [] and card_miss["lastEvent"] is None, card_miss["lastEvent"]
    assert card_miss["engineInsightId"] is None and card_miss["trend"]["metricKey"] == "margin", card_miss
    repo.delete_watch_target(t_miss)  # 自清理：漏删会让每次门禁往开发库塞一条「华东订单量」脏委托


    # ③ 无序列不编造：metric_key 不存在 / dimension 不匹配 / 无 intent → None
    t_bad_key = make("不存在指标", "no_such_metric", "", {"type": "below", "ref": 1.0})
    assert card_of(t_bad_key)["trend"] is None, "unknown metric_key must not fabricate points"
    t_bad_dim = make("口径不匹配", key, "南极", {"type": "below", "ref": 1.0})
    assert card_of(t_bad_dim)["trend"] is None, "dimension mismatch must not fabricate points"
    t_no_intent = repo.create_watch_target("无解析结果", {}, frequency="on_update")["id"]
    assert card_of(t_no_intent)["trend"] is None, "missing intent must yield null trend"
    for tid in (t_bad_key, t_bad_dim, t_no_intent):
        repo.delete_watch_target(tid)

    # 纯函数边界：窗口只影响展示（13 点 → 末尾 12）、方向按全序列、首点 0 → changePct null、空 → None
    many = [{"label": f"T{i}", "value": float(i), "dimension": dim, "unit": ""} for i in range(13)]
    t13 = build_trend(many, key, dim)
    assert len(t13["points"]) == 12 and t13["points"][0]["label"] == "T1" and t13["runDays"] == 12, t13
    zero_first = build_trend(
        [{"label": "T0", "value": 0.0, "dimension": dim, "unit": ""},
         {"label": "T1", "value": 1.0, "dimension": dim, "unit": ""}], key, dim)
    assert zero_first["changePct"] is None, "first point 0 → changePct null（不编造百分比）"
    assert build_trend([], key, dim) is None and build_trend(many, key, "南极") is None

    run_seed()  # 恢复出厂（清理 crafted 序列与事件）


def section6_handoff(repo: Repository) -> None:
    """watch-escalate-handoff：升级即移交（终态 / 凭据约束 / 恢复+去重仍移交 / 重置归位 /
    backfill 幂等 / 卡片三态 / 置态限制 / check 守卫）。

    自带清理：crafted 委托用完删除（main() 另有「无残留委托」守卫兜底）。
    前置：后端在运行（§4 已依赖）；末尾重建真实委托事件（本节 ⑤ 的清事件是破坏性的）。
    """
    import json
    import urllib.error
    import urllib.request
    from datetime import datetime, timezone

    from app.repository import WATCH_CLIENT_STATUSES, WATCH_STATUSES, WATCH_TERMINAL_STATUS
    from app.routers import _watch_card
    from app.watch.evaluator import evaluate_all
    from app.watch.scheduler import _is_due

    from tests.e2e_api_check import BASE, opener

    key, dim = "east_orders", "华东"
    crafted: list[str] = []

    def put(values, unit=""):
        repo.replace_series([key], [
            {"metric_key": key, "label": f"T{i}", "dimension": dim, "value": float(v), "unit": unit}
            for i, v in enumerate(values)
        ])

    def make(text, status=None, dimension=dim):
        kwargs = {"frequency": "on_update"}
        if status:
            kwargs["status"] = status
        tid = repo.create_watch_target(
            text,
            {"metric_key": key, "dimension": dimension, "label": "华东订单量",
             "condition": {"type": "streak_below", "days": 3, "ref": None}},
            **kwargs)["id"]
        crafted.append(tid)
        return tid

    def http_status(method: str, path: str, payload=None):
        req = urllib.request.Request(
            BASE + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    # ---------- ① 升级即终态：事件写入即移交，终态退出评估 ----------
    run_seed()
    put([105.0, 103.0, 100.0, 97.0, 93.0], "%")
    t_esc = make("移交-终态")
    evaluate_all(repo)
    evs = repo.list_watch_events(t_esc)
    assert len(evs) == 1 and evs[0]["kind"] == "escalate", evs
    assert evs[0]["values"]["engine_insight"] == "e2", evs
    tg = repo.get_watch_target(t_esc)
    assert tg["status"] == WATCH_TERMINAL_STATUS, f"escalate must hand off: {tg['status']}"
    frozen = tg["last_checked_at"]
    evaluate_all(repo)
    assert repo.list_watch_events(t_esc) == evs, "terminal target must not be re-evaluated"
    assert repo.get_watch_target(t_esc)["last_checked_at"] == frozen, "terminal last_checked_at frozen"
    assert _is_due(tg, datetime.now(timezone.utc)) is False, "terminal target is not due"

    # ---------- ② 凭据约束：每条 escalated 委托的最新事件必为 escalate 且带引擎洞察 id ----------
    scanned = 0
    for t in repo.list_watch_targets():
        if t["status"] != WATCH_TERMINAL_STATUS:
            continue
        scanned += 1
        last = (repo.list_watch_events(t["id"]) or [None])[-1]
        assert last is not None and last["kind"] == "escalate", f"escalated without credential: {t['id']}"
        assert (last.get("values") or {}).get("engine_insight"), f"escalate must quote engine insight: {t['id']}"
    assert scanned >= 1, "credential scan must be non-vacuous（至少一条 escalated 委托被检查）"

    # ---------- ③ 恢复（非破坏性、幂等）+ 去重仍移交 ----------
    assert repo.set_watch_status(t_esc, "watching")["status"] == "watching"
    assert repo.set_watch_status(t_esc, "watching")["status"] == "watching", "restore must be idempotent"
    assert len(repo.list_watch_events(t_esc)) == 1, "restore must NOT delete the escalate event"
    evaluate_all(repo)  # 数据未变 → 事件去重跳过，但"升级即移交"仍须成立
    assert len(repo.list_watch_events(t_esc)) == 1, "dedup: no duplicate escalate event"
    assert repo.get_watch_target(t_esc)["status"] == WATCH_TERMINAL_STATUS, \
        "dedup-skipped escalate must still hand off"

    # ---------- ④ 置态限制：客户端不可置终态；终态只可恢复 ----------
    for bad in ("escalated", "unknown"):
        try:
            repo.set_watch_status(t_esc, bad)
            raise AssertionError(f"status {bad!r} must be rejected")
        except ValueError:
            pass
    try:
        repo.set_watch_status(t_esc, "paused")
        raise AssertionError("escalated→paused must be rejected")
    except ValueError:
        pass
    try:
        repo.create_watch_target("非法创建", {"metric_key": key, "dimension": dim}, status="escalated")
        raise AssertionError("create(escalated) must be rejected")
    except ValueError:
        pass
    assert WATCH_CLIENT_STATUSES == {"watching", "paused"} and WATCH_TERMINAL_STATUS in WATCH_STATUSES

    # ---------- ⑤ 重置归位：清事件 → escalated 归位 watching（委托保留）；paused 不受影响 ----------
    t_keep = make("重置-paused", status="paused")
    assert repo.get_watch_target(t_esc)["status"] == WATCH_TERMINAL_STATUS  # 前置：确有终态
    repo.delete_all_watch_events()
    assert repo.get_watch_target(t_esc)["status"] == "watching", "reset must归位 terminal → watching"
    assert repo.list_watch_events(t_esc) == [], "events cleared by reset"
    assert repo.get_watch_target(t_esc) is not None, "reset MUST keep the target (非破坏性)"
    assert repo.get_watch_target(t_keep)["status"] == "paused", "paused untouched by reset"

    # ---------- ⑥ backfill 幂等：legacy（watching + escalate 事件）→ escalated；paused 不覆盖 ----------
    t_legacy = make("legacy-升级")
    repo.add_watch_event(t_legacy, "escalate", "历史遗留", {"engine_insight": "e2"})  # 旧写法：不置态
    t_legacy_paused = make("legacy-paused", status="paused")
    repo.add_watch_event(t_legacy_paused, "escalate", "历史遗留", {"engine_insight": "e2"})
    assert repo.get_watch_target(t_legacy)["status"] == "watching", "legacy fixture must start in-hand"
    moved1 = repo.backfill_watch_escalation()
    moved2 = repo.backfill_watch_escalation()
    assert moved1 >= 1 and moved2 == 0, f"backfill must be idempotent: {(moved1, moved2)}"
    assert repo.get_watch_target(t_legacy)["status"] == WATCH_TERMINAL_STATUS, "legacy must be migrated"
    assert repo.get_watch_target(t_legacy_paused)["status"] == "paused", "paused must NOT be backfilled"

    # ---------- ⑦ 卡片三态：value/color 由 status 派生（不再由末条事件现算） ----------
    t_card = make("卡片三态")
    assert (lambda c: (c["value"], c["color"]))(_watch_card(repo, repo.get_watch_target(t_card))) == \
        ("观察中", "green")
    repo.add_watch_event(t_card, "change", "命中变化", {"n": 1})
    card = _watch_card(repo, repo.get_watch_target(t_card))
    assert (card["value"], card["color"]) == ("有变化", "blue"), card
    repo.add_watch_event(t_card, "escalate", "已升级", {"engine_insight": "e2"}, escalate=True)
    card = _watch_card(repo, repo.get_watch_target(t_card))
    assert (card["status"], card["value"], card["color"], card["engineInsightId"]) == \
        ("escalated", "已升级", "red", "e2"), card
    repo.set_watch_status(t_card, "watching")
    repo.set_watch_status(t_card, "paused")
    card = _watch_card(repo, repo.get_watch_target(t_card))
    assert (card["value"], card["color"]) == ("已暂停", "blue"), card
    try:
        repo.add_watch_event(t_card, "escalate", "不该发生", {"engine_insight": "e2"}, escalate=True)
        raise AssertionError("escalate on paused must raise（暂停态不该产生升级事件）")
    except ValueError:
        pass

    # ---------- ⑧ HTTP 边界：check 守卫（仅 watching 可评估）+ PATCH 迁移矩阵 ----------
    t_chk = make("check-在手")
    code, body = http_status("POST", f"/watch/{t_chk}/check")
    assert code == 200 and json.loads(body)["ok"], (code, body)
    assert repo.get_watch_target(t_chk)["status"] == WATCH_TERMINAL_STATUS, "check hit must hand off"
    code, body = http_status("POST", f"/watch/{t_card}/check")  # paused
    assert code == 400 and "已暂停" in json.loads(body)["detail"], (code, body)
    code, body = http_status("POST", f"/watch/{t_legacy}/check")  # escalated
    assert code == 400 and "已升级移交" in json.loads(body)["detail"], (code, body)
    code, body = http_status("PATCH", f"/watch/{t_legacy}", {"status": "paused"})
    assert code == 400, (code, body)
    code, body = http_status("PATCH", f"/watch/{t_legacy}", {"status": "escalated"})
    assert code == 400, (code, body)
    code, body = http_status("PATCH", f"/watch/{t_legacy}", {"status": "watching"})
    assert code == 200 and json.loads(body)["target"]["status"] == "watching", (code, body)
    code, body = http_status("PATCH", "/watch/w-does-not-exist", {"status": "watching"})
    assert code == 404, (code, body)

    # ---------- 清理 + 重建真实委托事件（本节 ⑤ 清空过全库事件） ----------
    for tid in crafted:
        repo.delete_watch_target(tid)
    run_seed()
    repo.delete_all_watch_events()  # 与 /datasets/sample 的中间步一致：出厂态
    evaluate_all(repo)              # 重建：真实委托重新评估（命中则重新移交）
    print("  §6 升级即移交：终态/凭据/恢复/重置归位/backfill/卡片三态/置态限制/check 守卫 + 重建真实事件")



def main() -> int:
    run_seed()  # 建表 + 出厂重置（watch 表无种子，恒空起步）
    repo = Repository()
    # 污染守卫：门禁跑完不得在开发库新增委托（历史坑：§5 的 t_miss 漏删 → 每次 run_all 多一张
    # 同名「华东订单量」卡片；本断言让任何将来的漏删当场红，而不是靠人眼发现页面变脏）。
    before = {t["id"] for t in repo.list_watch_targets()}
    section1_crud(repo)
    section2_parser()
    section3_evaluator(repo)
    section4_e2e(repo)
    section5_trend(repo)
    section6_handoff(repo)
    leftover = {t["id"] for t in repo.list_watch_targets()} - before
    assert not leftover, f"watch_check 必须自清理：残留委托 {sorted(leftover)}"
    print("watch_check OK（第 1 节 CRUD + 第 2 节 解析 + 第 3 节 评估器 + 第 4 节 升级 E2E + 第 5 节 走向摘要/判定引用 + 第 6 节 升级即移交 全绿 + 无残留委托）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
