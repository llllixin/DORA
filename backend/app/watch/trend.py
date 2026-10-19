"""V4 watch 走向摘要（迭代 47）：把引擎同源时间线压成前端可直接渲染的走向。

- **口径与评估器完全同源**：输入 = `repo.get_series(metric_key)` → `chrono_points(rows, dimension)`
  （与 `evaluator.evaluate_one` 求值用的是同一条时间线），不新造第二条判定链。
- 展示窗口只影响 `points` / `changePct`；`direction` / `runDays` 按**全序列**算
  （直接复用 evaluator 的 `_decline_run` / `_rise_run`，与 `_eval_condition` 同一输入）。
- 时间线为空 → `None`（前端显示「暂无序列」，绝不编造点位）。
"""
from app.watch.evaluator import _decline_run, _rise_run, chrono_points

# 走向列 sparkline 的展示窗口（末尾 N 点）
LIMIT = 12


def _unit_of(rows: list[dict], dimension: str) -> str:
    """单位取该口径的第一行（无匹配行 → 空串，不猜）。"""
    for r in rows:
        if not dimension or r["dimension"] == dimension:
            return r.get("unit") or ""
    return ""


def build_trend(rows: list[dict], metric_key: str, dimension: str, limit: int = LIMIT) -> dict | None:
    """构造卡片 `trend` 摘要。

    `changePct` = 展示窗口首末相对变化（按首点绝对值归一，首点为 0 → `None`），保留 1 位小数。
    """
    timeline = chrono_points(rows, dimension)
    if not timeline:
        return None
    values = [v for _, v in timeline]
    down, up = _decline_run(values), _rise_run(values)
    if down > 0:
        direction, run_days = "down", down
    elif up > 0:
        direction, run_days = "up", up
    else:
        direction, run_days = "flat", 0
    window = timeline[-limit:] if limit and limit > 0 else timeline
    first, last = window[0][1], window[-1][1]
    change_pct = None if first == 0 else round((last - first) / abs(first) * 100, 1)
    return {
        "metricKey": metric_key,
        "dimension": dimension,
        "unit": _unit_of(rows, dimension),
        "points": [{"label": lab, "value": val} for lab, val in window],
        "direction": direction,
        "runDays": run_days,
        "changePct": change_pct,
        "basis": (
            f"近 {len(window)} 点 · 方向按全序列（{len(values)} 点）"
            f" · 引擎口径 {metric_key}/{dimension or '全量'}"
        ),
    }
