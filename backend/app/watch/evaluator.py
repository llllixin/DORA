"""V4-T3 通用 Watch 评估器：把委托 condition 对引擎同源时间序列求值。

- 值口径与引擎一致：全部来自 repo.get_series（engine 同源）。
- dimension=="" → 按 label 同周期跨维度聚合（均值）构造时间线（returns 门店级即此类）。
- escalate 红线：仅当引擎 run_engine 已产出 ESCALATION[key] 对应洞察时才升级并引用该 insight id。
- 去重：与最近一条事件 kind+values 相同则跳过（幂等重评估/重置不刷屏）。
"""
from datetime import datetime, timezone

from app.engine.engine import _mean, run_engine
from app.repository import Repository

# 引擎 problem/opportunity insight id（metric_key → insight id）——升级身份只认引擎判定
ESCALATION = {
    "margin": "p1",
    "returns": "p2",
    "orders": "p3",
    "aov": "o1",
    "east_orders": "e2",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _chrono_values(rows: list[dict], dimension: str) -> list[float]:
    """时间序列值：单 dimension 直取；dimension=="" 按 label 周期跨维度均值聚合。"""
    if not rows:
        return []
    if dimension:
        return [r["value"] for r in rows if r["dimension"] == dimension]
    # 整表聚合：同一 label（观察期）跨维度取均值，顺序按 label 首次出现
    by_label: dict[str, list[float]] = {}
    order: list[str] = []
    for r in rows:
        lab = r["label"]
        if lab not in by_label:
            by_label[lab] = []
            order.append(lab)
        by_label[lab].append(r["value"])
    return [_mean(by_label[lab]) for lab in order]


def _decline_run(values: list[float]) -> int:
    n = 0
    for i in range(len(values) - 1, 0, -1):
        if values[i] < values[i - 1]:
            n += 1
        else:
            break
    return n


def _rise_run(values: list[float]) -> int:
    n = 0
    for i in range(len(values) - 1, 0, -1):
        if values[i] > values[i - 1]:
            n += 1
        else:
            break
    return n


def _eval_condition(cond: dict | None, values: list[float]) -> bool:
    if not cond or not values:
        return False
    ctype = cond.get("type")
    if ctype == "streak_below":
        return _decline_run(values) >= int(cond.get("days") or 1)
    if ctype == "streak_above":
        return _rise_run(values) >= int(cond.get("days") or 1)
    if ctype == "below":
        return values[-1] < float(cond.get("ref") or 0)
    if ctype == "above":
        return values[-1] > float(cond.get("ref") or 0)
    return False


def evaluate_one(repo: Repository, target: dict, engine_insights: list[dict] | None = None) -> dict:
    """评估单个委托；返回 {hit, kind: change|escalate|miss, event?, skipped?}。"""
    intent = target.get("intent") or {}
    key = intent.get("metric_key")
    dimension = intent.get("dimension", "")
    cond = intent.get("condition")
    if not key or not cond:
        return {"hit": False, "kind": "miss", "event": None, "skipped": False}

    rows = repo.get_series(key)
    values = _chrono_values(rows, dimension)
    hit = _eval_condition(cond, values)
    if not hit:
        return {"hit": False, "kind": "miss", "event": None, "skipped": False}

    cur = values[-1]
    prev = values[-2] if len(values) > 1 else cur
    base_values = {
        "metric_key": key, "dimension": dimension,
        "prev": prev, "cur": cur,
        "unit": rows[0].get("unit", "") if rows else "",
    }
    label = intent.get("label") or key

    # 升级身份只认引擎判定（红线）
    pid = ESCALATION.get(key)
    eng = None
    if pid is not None and engine_insights:
        eng = next((x for x in engine_insights if x.get("id") == pid), None)
    if eng is not None:
        kind, summary = "escalate", f"已升级：{eng.get('trigger') or eng.get('title') or pid}"
        values = {**base_values, "engine_insight": pid, "engine_type": eng.get("type")}
    else:
        cond_type = cond.get("type")
        if cond_type == "below":
            summary = f"{label}跌破 {cond.get('ref')}（最新 {cur}）"
        elif cond_type == "above":
            summary = f"{label}超过 {cond.get('ref')}（最新 {cur}）"
        elif cond_type == "streak_above":
            summary = f"{label}连续 {cond.get('days')} 天上涨（最新 {cur}）"
        else:
            summary = f"{label}连续 {cond.get('days')} 天下降（最新 {cur}）"
        kind = "change"
        values = dict(base_values)

    events = repo.list_watch_events(target["id"])
    last = events[-1] if events else None
    if last is not None and last["kind"] == kind and last["values"] == values:
        return {"hit": True, "kind": kind, "event": None, "skipped": True}

    ev = repo.add_watch_event(target["id"], kind, summary, values)
    return {"hit": True, "kind": kind, "event": ev, "skipped": False}


def evaluate_all(repo: Repository, freqs: tuple[str, ...] = ("on_update",),
                 engine_insights: list[dict] | None = None) -> dict:
    """批量评估 watching 委托；run_engine 只算一次共享。返回计数。"""
    counts = {"checked": 0, "change": 0, "escalate": 0, "miss": 0, "skipped": 0}
    targets = [
        t for t in repo.list_watch_targets()
        if t["status"] == "watching" and (t.get("frequency") or "on_update") in freqs
    ]
    if not targets:
        return counts
    insights = engine_insights if engine_insights is not None else run_engine(repo)["insights"]
    now = _now_iso()
    for t in targets:
        out = evaluate_one(repo, t, insights)
        counts["checked"] += 1
        if out["kind"] != "miss":
            counts[out["kind"]] += 1 if not out["skipped"] else 0
            if out["skipped"]:
                counts["skipped"] += 1
        else:
            counts["miss"] += 1
        repo.touch_watch_target(t["id"], now)
    return counts
