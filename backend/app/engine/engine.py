"""V2 确定性业务引擎（Metric → Rule → Signal → Insight）。

定位：
- 数据源：Repository（默认 PostgreSQL）；`dataset.py` 仅作种子源。
- 规则阈值默认值收敛在 RULE_DEFAULTS（engine），DB `rule_config` 有值优先（_rule_map）。
- 判定为确定性计算；叙事文案用模板占位，待 V3 Reasoning 替换文本层。
- 引擎不依赖 LLM / Agent（D009/D014），证据行由 Repository 数据生成。
"""
from app.repository import Repository  # noqa: F401 (engine_evidence 默认数据源)


def _pct(cur: float, prev: float) -> float:
    return (cur / prev - 1.0) * 100.0


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _below(actual: float, ref: float) -> bool:
    """阈值比较：'低于目标' 用严格小于（值==目标不触发）。"""
    return actual < ref


def _breach(actual: float, threshold: float, *, inclusive: bool = True) -> bool:
    """阈值比较：'跌破升级阈值' 默认含等于（<=）；inclusive=False 时严格小于。"""
    return actual <= threshold if inclusive else actual < threshold


def _streak_below(values: list[float], target: float) -> int:
    n = 0
    for v in reversed(values):
        if _below(v, target):
            n += 1
        else:
            break
    return n


RULE_DEFAULTS = {
    "margin.target": 18.5,
    "returns.baseline": 3.2,
    "east.threshold": -3.0,
    "store_cluster.ratio": 60.0,
    "store_cluster.mix_name": "新品系列渗透率",
    "store_cluster.mix_pct": 82.0,
}


def _rule_map(repo) -> dict:
    """规则配置：DB 有值优先，缺省回退内置默认。"""
    return {**RULE_DEFAULTS, **(repo.get_rules() if repo else {})}


def _series(repo, key: str, dimension: str | None = None) -> list[float]:
    """从 Repository 读取某指标（可按维度过滤）时间序列值（按存储顺序=时间序）。"""
    if repo is None:
        return []
    return [r["value"] for r in repo.get_series(key) if dimension is None or r["dimension"] == dimension]


from datetime import datetime

from app.reasoning.semantics import template_semantics as _semantics

METRIC_SERIES_KEYS = [
    "margin", "returns", "orders", "revenue", "aov",
    "east_orders", "new_sku", "high_value", "supplier_price",
]


def _repo_has_series(repo) -> bool:
    """空数据门禁：Repository 是否存在任一指标序列。"""
    return any(bool(repo.get_series(key)) for key in METRIC_SERIES_KEYS)


def compute_snapshot(repo=None, rules=None) -> dict:
    """从 Repository（默认 PostgreSQL）读取原始数据并计算指标状态。"""
    rules = rules or _rule_map(repo)
    margin = _series(repo, "margin", "全国")
    orders = _series(repo, "orders", "全国")
    revenue = _series(repo, "revenue", "全国")
    aov = _series(repo, "aov", "全国")
    east = _series(repo, "east_orders", "华东")
    new_sku = _series(repo, "new_sku", "全区域")
    high = _series(repo, "high_value", "全国")
    target = float(rules["margin.target"])
    baseline = float(rules["returns.baseline"])

    # 退货：按门店维度分组
    store_rows = repo.get_series("returns") if repo else []
    returns_by_store: dict[str, list[float]] = {}
    for r in store_rows:
        returns_by_store.setdefault(r["dimension"], []).append(r["value"])
    latest_store = {s: vals[-1] for s, vals in returns_by_store.items()}

    # 供应商价格：按供应商维度分组
    price_rows = repo.get_series("supplier_price") if repo else []
    price_by_supplier: dict[str, list[float]] = {}
    for r in price_rows:
        price_by_supplier.setdefault(r["dimension"], []).append(r["value"])
    b_prices = price_by_supplier.get("供应商B", [])
    c_prices = price_by_supplier.get("供应商C", [])

    # 门店集群：从行聚合（Top 列表默认全表 = 种子 10 家）
    cluster_rows = repo.get_cluster_stores() if repo else []
    region_counts: dict[str, int] = {}
    region_aov: dict[str, list[float]] = {}
    for cr in cluster_rows:
        region_counts[cr["region"]] = region_counts.get(cr["region"], 0) + 1
        region_aov.setdefault(cr["region"], []).append(cr["aov"])
    region = max(region_counts, key=lambda k: (region_counts[k], k)) if region_counts else ""
    region_count = region_counts.get(region, 0)
    top_total = len(cluster_rows)

    event = repo.get_latest_update() if repo else None
    event = event or {"updated": "--", "rows_added": 0, "total_rows": 0, "metrics": []}

    return {
        "margin": {
            "current": margin[-1] if margin else 0.0,
            "baseline": _mean(margin[:4]) if len(margin) >= 4 else (margin[0] if margin else 0.0),
            "target": target,
            "delta_pct": round(_pct(margin[-1], _mean(margin[:4])), 1) if len(margin) >= 4 else 0.0,
            "streak_below": _streak_below(margin, target) if margin else 0,
            "latest": margin[-3:],
        },
        "returns": {
            "latest_store": latest_store,
            "baseline": baseline,
            "delta_pp": round((max(latest_store.values()) if latest_store else 0.0) - baseline, 1),
            "stores": list(returns_by_store.keys()),
            "rising_weeks": min((len(v) for v in returns_by_store.values()), default=0),
        },
        "orders": {
            "current": int(orders[-1]) if orders else 0,
            "delta_pct": round(_pct(orders[-1], _mean(orders[:2])), 1) if len(orders) >= 2 else 0.0,
        },
        "revenue": {
            "current": int(revenue[-1]) if revenue else 0,
            "delta_pct": round(_pct(revenue[-1], _mean(revenue[:2])), 1) if len(revenue) >= 2 else 0.0,
        },
        "aov": {
            "current": int(aov[-1]) if aov else 0,
            "delta_pct": round(_pct(aov[-1], _mean(aov[:2])), 1) if len(aov) >= 2 else 0.0,
        },
        "east_orders": {
            "current": int(east[-1]) if east else 0,
            "delta_pct": round(_pct(east[-1], _mean(east[:2])), 1) if len(east) >= 2 else 0.0,
            "threshold": float(rules["east.threshold"]),
        },
        "new_sku": {
            "current": int(new_sku[-1]) if new_sku else 0,
            "delta_pct": round(_pct(new_sku[-1], new_sku[0]), 1) if new_sku else 0.0,
        },
        "high_value": {
            "current": high[-1] if high else 0.0,
            "baseline": high[0] if high else 0.0,
            "delta_pp": round((high[-1] - high[0]) if high else 0.0, 1),
        },
        "data_event": {
            "updated": event["updated"],
            "rows_added": event["rows_added"],
            "total_rows": event["total_rows"],
            "metrics": event["metrics"],
        },
        "store_cluster": {
            "region": region,
            "top_total": top_total,
            "region_count": region_count,
            "ratio": round(region_count / top_total * 100.0, 1) if top_total else 0.0,
            "threshold": float(rules["store_cluster.ratio"]),
            "aov": round(_mean(region_aov.get(region, [])), 1) if region_aov.get(region) else 0.0,
            "mix_name": str(rules["store_cluster.mix_name"]),
            "mix_pct": float(rules["store_cluster.mix_pct"]),
        },
        "supplier_b": {
            "current": b_prices[-1] if b_prices else 0.0,
            "delta_pct": round(_pct(b_prices[-1], _mean(b_prices[:-1])), 1) if len(b_prices) > 1 else 0.0,
            "peer_delta_pct": round(_pct(b_prices[-1], c_prices[-1]), 1) if b_prices and c_prices else 0.0,
        },
    }



def evaluate_signals(snap: dict) -> list[dict]:
    """规则求值：把指标状态翻译为候选信号（Signal ≠ Insight）。"""
    signals = []
    m, r = snap["margin"], snap["returns"]
    o, rev, a = snap["orders"], snap["revenue"], snap["aov"]
    e, n, h, b = snap["east_orders"], snap["new_sku"], snap["high_value"], snap["supplier_b"]
    u, sc = snap["data_event"], snap["store_cluster"]

    if m["streak_below"] >= 3:
        signals.append({
            "id": "sig-margin", "insight": "p1", "type": "problem", "metric_key": "margin",
            "metric": f"{m['current']}%", "delta": f"↓ {abs(m['delta_pct'])}%",
            "trigger": f"连续 {m['streak_below']} 天低于目标 {m['target']}%",
            "factors": [f"A 产品线采购成本变化 {b['delta_pct']}%", f"供应商 B 较同行高 {abs(b['peer_delta_pct'])}%"],
            "evidence_kind": "margin",
        })
    if r["delta_pp"] >= 1.0 and r["rising_weeks"] >= 4:
        signals.append({
            "id": "sig-returns", "insight": "p2", "type": "problem", "metric_key": "returns",
            "metric": f"{max(r['latest_store'].values())}%", "delta": f"↑ {r['delta_pp']}pp",
            "trigger": "退货率高于区域基线，连续多周上升且集中于少数门店",
            "factors": [f"高贡献门店：{' / '.join(r['stores'])}"],
            "evidence_kind": "returns",
        })
    if o["delta_pct"] < -1.5 and rev["delta_pct"] > 2.0:
        signals.append({
            "id": "sig-order-structure", "insight": "p3", "type": "problem", "metric_key": "orders",
            "metric": f"{o['current']:,}", "delta": f"↓ {abs(o['delta_pct'])}%",
            "trigger": "订单量下滑而销售额逆势增长，结构信号需要复核",
            "factors": [f"销售额 ↑ {rev['delta_pct']}%", f"客单价 ↑ {a['delta_pct']}%"],
            "evidence_kind": "orders",
        })
    if a["delta_pct"] >= 4.0:
        signals.append({
            "id": "sig-aov", "insight": "o1", "type": "opportunity", "metric_key": "aov",
            "metric": f"¥{a['current']:,}", "delta": f"↑ {a['delta_pct']}%",
            "trigger": "客单价持续抬升，趋势具备可复制假设",
            "factors": ["需拆解价格与商品结构贡献"],
            "evidence_kind": "aov",
        })
    if e["delta_pct"] < -1.0:
        if _breach(e["delta_pct"], e["threshold"]):  # 跌破默认含等于
            # Watch→升级：跌破阈值自动升级为问题（文档 Case 4）
            signals.append({
                "id": "sig-east-breach", "insight": "e2", "type": "problem", "metric_key": "east_orders",
                "metric": f"{e['current']:,}", "delta": f"↓ {abs(e['delta_pct'])}%",
                "trigger": f"华东订单量跌破升级阈值 {e['threshold']}%，自动升级为问题",
                "factors": ["跌破阈值，已自动升级；建议进入行动回路定位原因"],
                "evidence_kind": "east_orders",
            })
        else:
            signals.append({
                "id": "sig-east-orders", "insight": "c1", "type": "change", "metric_key": "east_orders",
                "metric": f"{e['current']:,}", "delta": f"↓ {abs(e['delta_pct'])}%",
                "trigger": f"未达升级阈值 {e['threshold']}%，保持观察",
                "factors": ["继续观察，跌破阈值自动升级问题"],
                "evidence_kind": "east_orders",
            })
    if n["delta_pct"] >= 30:
        signals.append({
            "id": "sig-new-sku", "insight": "c3", "type": "change", "metric_key": "new_sku",
            "metric": f"{n['current']:,}", "delta": f"↑ {n['delta_pct']}%",
            "trigger": "新品连续增长但缺少门店共性验证，暂为机会候选",
            "factors": ["需拆解增长门店与动作"],
            "evidence_kind": "new_sku",
        })
    if h["delta_pp"] >= 5:
        signals.append({
            "id": "sig-high-value", "insight": "c4", "type": "change", "metric_key": "high_value",
            "metric": f"{h['current']}%", "delta": f"↑ {h['delta_pp']}pp",
            "trigger": "高客单门店占比结构性抬升，暂不单独升级",
            "factors": ["与客单价/订单洞察联动观察"],
            "evidence_kind": "high_value",
        })
    if u["rows_added"] > 0:
        signals.append({
            "id": "sig-data-event", "insight": "c2", "type": "change", "metric_key": "data_event",
            "metric": f"+{u['rows_added']} 条", "delta": f"{u['updated']} 更新",
            "trigger": f"数据更新事件：新增 {u['rows_added']} 条记录，Dora 已重算核心指标",
            "factors": [f"受影响指标：{'、'.join(u['metrics'])}"],
            "evidence_kind": "data_event",
        })
    if sc["ratio"] >= sc["threshold"]:
        signals.append({
            "id": "sig-store-cluster", "insight": "o2", "type": "opportunity", "metric_key": "store_cluster",
            "metric": f"{sc['region_count']} / {sc['top_total']}",
            "delta": f"{sc['region']}占比 {sc['ratio']:.0f}%",
            "trigger": f"Top 高客单门店集中于{sc['region']}，形成可复制机会假设",
            "factors": [f"{sc['mix_name']} {sc['mix_pct']:.0f}%"],
            "evidence_kind": "store_cluster",
        })
    return signals


# 洞察叙事模板：承载"判断文案"；数值字段由信号动态注入（V3 用 Reasoning 替换模板）
INSIGHT_TEMPLATES = {
    "p1": {"tag": "问题 · 高影响", "title": "利润率低于目标", "desc": "连续 {streak} 天低于目标，成本端出现可干预因素。", "source": "趋势 + 产品线 + 供应商（引擎计算）", "question": "成本上涨集中在哪个供应商？"},
    "p2": {"tag": "问题 · 中影响", "title": "区域退货率持续上行", "desc": "退货率高于基线且集中于少数高贡献门店。", "source": "退货明细 + 门店维度（引擎计算）", "question": "高频退货的商品与原因是什么？"},
    "p3": {"tag": "问题 · 需复核", "title": "订单量下降但销售额仍增长", "desc": "订单与销售额反向，结构变化需拆开复核。", "source": "订单 + 销售额 + 客单价（引擎计算）", "question": "增长是否由少数高价值订单贡献？"},
    "o1": {"tag": "增长机会", "title": "客单价连续抬升", "desc": "客单价呈持续上升趋势，具备复制假设。", "source": "客单价 + 商品 + 门店（引擎计算）", "question": "这个增长能复制吗？"},
    "c1": {"tag": "观察中", "title": "华东订单量偏弱", "desc": "订单量下滑但未达升级阈值，保持观察。", "source": "华东订单 + 阈值规则（引擎计算）", "question": "为什么还没有升级成问题？"},
    "c3": {"tag": "趋势出现", "title": "新品销量快速增长", "desc": "新品销量高增但尚未完成机会确认。", "source": "新品销量 + 周趋势（引擎计算）", "question": "增长门店有没有共同动作？"},
    "c4": {"tag": "结构变化", "title": "高客单门店占比抬升", "desc": "门店结构正朝高价值方向迁移。", "source": "门店分层 + 客单价（引擎计算）", "question": "结构变化是否稳定？"},
    "e2": {"tag": "问题 · 自动升级", "title": "华东订单量跌破升级阈值", "desc": "连续下滑已突破升级阈值，Dora 自动升级为问题。", "source": "华东订单 + 阈值规则（引擎计算）", "question": "如何遏制华东订单量下滑？"},
    "c2": {"tag": "数据更新", "title": "门店销售数据已更新", "desc": "09:32 新增 {rows_added} 条记录，Dora 已重新计算主动发现。", "source": "数据源状态（引擎计算）", "question": "这次更新影响了哪些指标？"},
    "o2": {"tag": "增长机会", "title": "高客单门店形成集群", "desc": "Top 高客单门店集中于华东，存在可复制的经营假设。", "source": "门店画像 + 客单价（引擎计算）", "question": "这些门店做对了什么？"},
}


def _confidence(sig: dict) -> int:
    base = 70 if sig["type"] == "change" else 75
    return min(99, base + len(sig["factors"]) * 3 + (5 if len(sig.get("trigger", "")) > 12 else 0))




# ---- 洞察严重等级 / 可能后果（change insight-judgment-structure；design D1/D2、D040）----
# 判级口径集中在此常量：改口径 = 改这里一处 + 跑 engine_check（不进 DB、不入 reasoning 缓存）。
SEVERITY_WEIGHTS = {
    "base": {"problem": 50, "opportunity": 45, "change": 25},
    "trend_pct": ((10.0, 20), (5.0, 14), (3.0, 10), (1.5, 6)),  # 百分比量纲的偏离幅度分档
    "trend_pp": ((5.0, 20), (3.0, 14), (1.5, 10)),              # 百分点量纲的偏离幅度分档
    "trend_floor": 2,                                           # 有幅度但未达最小档
    "threshold": {"crossed": 12, "near1": 8, "near2": 5},       # 已越线 / 距线 <=1 / <=2
    "duration_per": 1.5, "duration_cap": 6,
    "impact_per": 2, "impact_cap": 4,
    "attribution_per": 2, "attribution_cap": 3,
    "level_high": 75, "level_medium": 55,
}

SEVERITY_LABEL = {"problem": "问题", "opportunity": "机会", "change": "变化"}


def _severity_measures(sig: dict, snap: dict) -> dict:
    """判级所需的快照量（全部由同一份 snap 派生，供文案生成与门禁回溯）。

    每项含义（None = 该洞察没有这个量）：
    - trend：(偏离幅度, 量纲 pct|pp, 文案名)
    - threshold：(是否已越线, 距线绝对值, 阈值线, 文案名)
    - duration：(连续量, 单位, 文案名)
    - impact：(受影响对象数, 单位, 文案名)
    - attribution：归因因素条数（来自信号）
    """
    m, r = snap["margin"], snap["returns"]
    e, n, h = snap["east_orders"], snap["new_sku"], snap["high_value"]
    o, a = snap["orders"], snap["aov"]
    sc, u = snap["store_cluster"], snap["data_event"]
    factors = len(sig.get("factors") or [])

    if sig["insight"] == "p1":
        return {"trend": (abs(m["delta_pct"]), "pct", "偏离目标"),
                "threshold": (m["current"] < m["target"], round(abs(m["current"] - m["target"]), 1),
                              m["target"], "距目标线"),
                "duration": (m["streak_below"], "天", "连续低于目标"),
                "impact": (1, "家", "受影响供应商"), "attribution": factors}
    if sig["insight"] == "p2":
        return {"trend": (abs(r["delta_pp"]), "pp", "高于基线"),
                "threshold": None,
                "duration": (r["rising_weeks"], "周", "连续上升"),
                "impact": (len(r["latest_store"]), "家", "受影响门店"), "attribution": factors}
    if sig["insight"] == "p3":
        return {"trend": (abs(o["delta_pct"]), "pct", "订单量偏离"),
                "threshold": None, "duration": (0, "天", ""),
                "impact": (2, "项", "受影响指标"),  # 信号口径：订单量 + 销售额
                "attribution": factors}
    if sig["insight"] == "o1":
        return {"trend": (a["delta_pct"], "pct", "高于常态"),
                "threshold": None, "duration": (0, "天", ""),
                "impact": (1, "项", "受影响指标"), "attribution": factors}
    if sig["insight"] in ("c1", "e2"):
        return {"trend": (abs(e["delta_pct"]), "pct", "偏离常态"),
                "threshold": (_breach(e["delta_pct"], e["threshold"]),
                              round(abs(e["delta_pct"] - e["threshold"]), 1), e["threshold"], "距升级阈值"),
                "duration": (0, "天", ""),
                "impact": (1, "个", "受影响区域"), "attribution": factors}
    if sig["insight"] == "c3":
        return {"trend": (n["delta_pct"], "pct", "高于常态"),
                "threshold": None, "duration": (0, "天", ""),
                "impact": (1, "项", "受影响指标"), "attribution": factors}
    if sig["insight"] == "c4":
        return {"trend": (h["delta_pp"], "pp", "高于基线"),
                "threshold": None, "duration": (0, "天", ""),
                "impact": (1, "项", "受影响指标"), "attribution": factors}
    if sig["insight"] == "c2":
        return {"trend": None, "threshold": None, "duration": (0, "天", ""),
                "impact": (len(u["metrics"]), "项", "受影响指标"), "attribution": factors}
    if sig["insight"] == "o2":
        return {"trend": None,
                "threshold": (sc["ratio"] >= sc["threshold"], round(sc["ratio"] - sc["threshold"], 1),
                              sc["threshold"], "距机会阈值"),
                "duration": (0, "天", ""),
                "impact": (sc["region_count"], "家", "受影响门店"), "attribution": factors}
    return {"trend": None, "threshold": None, "duration": (0, "天", ""),
            "impact": (1, "项", "受影响指标"), "attribution": factors}


def _trend_score(measures: dict, w: dict) -> float:
    """偏离幅度分档分（pct / pp 两套档位）。"""
    trend = measures.get("trend")
    if not trend:
        return 0.0
    table = w["trend_pct"] if trend[1] == "pct" else w["trend_pp"]
    for cut, points in table:
        if abs(trend[0]) >= cut:
            return float(points)
    return float(w["trend_floor"])


def _threshold_score(measures: dict, w: dict) -> float:
    """距阈值分档分（与 trend 取 max：两者度量同一件事，相加会重复计分）。"""
    thr = measures.get("threshold")
    if not thr:
        return 0.0
    crossed, distance, _line, _name = thr
    if crossed:
        return float(w["threshold"]["crossed"])
    if distance <= 1.0:
        return float(w["threshold"]["near1"])
    if distance <= 2.0:
        return float(w["threshold"]["near2"])
    return 0.0


def _severity_drivers(measures: dict) -> list[dict]:
    """参与判级的因子（值全部由快照量格式化，保证每个数字可回溯）。"""
    out: list[dict] = []
    trend = measures.get("trend")
    if trend:
        out.append({"name": trend[2], "value": f"{abs(trend[0])}{'%' if trend[1] == 'pct' else 'pp'}"})
    thr = measures.get("threshold")
    if thr:
        crossed, distance, _line, name = thr
        out.append({"name": name, "value": "已越线" if crossed else f"{distance}pp"})
    dur = measures.get("duration")
    if dur and dur[0]:
        out.append({"name": dur[2], "value": f"{dur[0]} {dur[1]}"})
    imp = measures.get("impact")
    if imp and imp[0]:
        out.append({"name": imp[2], "value": f"{imp[0]} {imp[1]}"})
    if measures.get("attribution"):
        out.append({"name": "归因因素", "value": f"{measures['attribution']} 项"})
    return out


def _severity(sig: dict, snap: dict) -> dict:
    """洞察严重等级：由同一份快照按 SEVERITY_WEIGHTS 显式加权（与 tag 文案无关）。"""
    w = SEVERITY_WEIGHTS
    me = _severity_measures(sig, snap)
    duration = min(me["duration"][0], w["duration_cap"]) * w["duration_per"]
    impact = min(me["impact"][0], w["impact_cap"]) * w["impact_per"]
    attribution = min(me["attribution"], w["attribution_cap"]) * w["attribution_per"]
    raw = (w["base"][sig["type"]] + max(_trend_score(me, w), _threshold_score(me, w))
           + duration + impact + attribution)
    score = int(round(min(99.0, raw)))
    level = "high" if score >= w["level_high"] else "medium" if score >= w["level_medium"] else "low"
    drivers = _severity_drivers(me)
    rule = (f"引擎启发式 · {SEVERITY_LABEL[sig['type']]}："
            + "、".join(f"{d['name']} {d['value']}" for d in drivers))
    return {"level": level, "score": score, "rule": rule, "drivers": drivers, "basis": "engine"}


def _consequence_of(summary: str, horizon: str, condition: str, impacts: list[tuple[str, str]]) -> dict:
    return {"summary": summary, "horizon": horizon, "condition": condition,
            "impacts": [{"name": k, "value": v} for k, v in impacts], "basis": "engine"}


def _consequence(sig: dict, snap: dict) -> dict:
    """洞察可能后果：按当前快照做确定性外推（只用快照数字；无趋势字段时给定性后果）。

    口径（design D2）：`summary` 以「若…」开头 + 强制 `condition`（前提）与 `horizon`（观察窗口）；
    `impacts` 的值只引用快照量；证据不足（c2 数据更新事件无趋势字段）→ 定性表述、不造数字。
    """
    m, r = snap["margin"], snap["returns"]
    e, n = snap["east_orders"], snap["new_sku"]
    o, rev, a = snap["orders"], snap["revenue"], snap["aov"]
    sc, u = snap["store_cluster"], snap["data_event"]
    ins = sig["insight"]

    if ins == "p1":
        return _consequence_of(
            f"若不干预，利润率将延续 {abs(m['delta_pct'])}% 的偏离幅度（当前 {m['current']}%，目标 {m['target']}%），成本端压力继续放大",
            f"{max(m['streak_below'], 3)} 天", "若成本端未干预",
            [("目标线", f"{m['target']}%"), ("当前利润率", f"{m['current']}%"), ("受影响供应商", "1 家")])
    if ins == "p2":
        latest = max(r["latest_store"].values()) if r["latest_store"] else 0.0
        return _consequence_of(
            f"若不处理，退货率将延续每周 {r['delta_pp']}pp 的上升（当前最高 {latest}%，基线 {r['baseline']}%），高贡献门店持续受损",
            f"{max(r['rising_weeks'], 3)} 周", "若退货原因未处理",
            [("基线", f"{r['baseline']}%"), ("当前最高门店退货率", f"{latest}%"), ("高于基线", f"{r['delta_pp']}pp")])
    if ins == "p3":
        return _consequence_of(
            f"若不复核，订单量 {abs(o['delta_pct'])}% 的下滑与销售额 {rev['delta_pct']}% 的增长将持续背离",
            "3 天", "若结构变化延续",
            [("订单量变化", f"{o['delta_pct']}%"), ("销售额变化", f"+{rev['delta_pct']}%")])
    if ins == "o1":
        return _consequence_of(
            f"若增长来源可复制，客单价将延续 {a['delta_pct']}% 的抬升（当前 ¥{a['current']:,}）",
            "2 周", "若增长来源可复制",
            [("当前客单价", f"¥{a['current']:,}"), ("增长率", f"{a['delta_pct']}%")])
    if ins == "c1":
        distance = round(abs(e["delta_pct"] - e["threshold"]), 1)
        return _consequence_of(
            f"若继续走弱，订单量再降 {distance}pp 即触及 {e['threshold']}% 升级阈值，将自动升级为问题",
            "5 天", "若趋势延续",
            [("当前偏离", f"{e['delta_pct']}%"), ("距升级阈值", f"{distance}pp"), ("升级阈值", f"{e['threshold']}%")])
    if ins == "e2":
        return _consequence_of(
            f"若不干预，华东订单量将延续 {abs(e['delta_pct'])}% 的下滑（已跌破 {e['threshold']}% 升级阈值）",
            "3 天", "若趋势延续",
            [("升级阈值", f"{e['threshold']}%"), ("当前偏离", f"{e['delta_pct']}%")])
    if ins == "c3":
        return _consequence_of(
            f"若增长延续，新品销量将继续以 {n['delta_pct']}% 的幅度抬升（当前 {n['current']:,} 件），需先验证增长门店的共性动作",
            "5 天", "若增长延续",
            [("当前销量", f"{n['current']:,}"), ("增长率", f"{n['delta_pct']}%")])
    if ins == "c4":
        h = snap["high_value"]
        return _consequence_of(
            f"若结构变化延续，高客单门店占比将在 {h['current']}% 基础上继续走高（高于基线 {h['delta_pp']}pp）",
            "5 天", "若结构变化延续",
            [("当前占比", f"{h['current']}%"), ("高于基线", f"{h['delta_pp']}pp")])
    if ins == "c2":
        # 证据不足路径：数据更新事件没有趋势/阈值字段 → 定性后果，不造新数字
        return _consequence_of(
            "数据事件本身不构成经营后果；重算后若指标触发阈值，将生成对应洞察",
            "下次更新前", "若重算结果触发阈值",
            [("受影响指标", f"{len(u['metrics'])} 项")])
    if ins == "o2":
        return _consequence_of(
            f"若可复制性成立，{sc['region']}高客单集群将从 {sc['region_count']} 家向更多门店扩散（当前占 Top {sc['top_total']} 家的 {sc['ratio']:.0f}%）",
            "2 周", "若可复制性成立",
            [("集群门店", f"{sc['region_count']} 家"), ("占 Top 门店", f"{sc['ratio']:.0f}%"),
             ("机会阈值", f"{sc['threshold']}%")])
    return _consequence_of("若当前状态延续，该洞察的影响面将保持现状，需结合证据链进一步定位",
                           "3 天", "若当前状态延续", [("受影响指标", "1 项")])


def build_insights(signals: list[dict], snap: dict) -> tuple[list[dict], dict]:
    """Signal → Insight：注入计算数值 + 生成置信度 + 汇总 Pulse。"""
    insights: list[dict] = []
    for sig in signals:
        tpl = INSIGHT_TEMPLATES[sig["insight"]]
        extra = {
            "streak": snap["margin"]["streak_below"],
            "rows_added": snap["data_event"]["rows_added"],
            "updated": snap["data_event"]["updated"],
        }
        insights.append({
            "id": sig["insight"],
            "type": sig["type"],
            "tag": tpl["tag"],
            "title": tpl["title"],
            "desc": tpl["desc"].format(**extra),
            "confidence": _confidence(sig),
            "metric": sig["metric"],
            "delta": sig["delta"],
            "source": tpl["source"],
            "question": tpl["question"],
            "trigger": sig["trigger"],
            "factors": sig["factors"],
            "evidence": {
                "kind": sig["evidence_kind"],
                "rows": [],  # 证据行由 engine_evidence 从 Repository 实时生成（cleanup）
            },
            "semantics": _semantics(sig["insight"], snap),
            # 增量字段（每算每出、不入库、不进 reasoning 缓存）：严重等级 + 可能后果
            "severity": _severity(sig, snap),
            "consequence": _consequence(sig, snap),
        })
    counts = {k: 0 for k in ("problems", "opportunities", "changes", "watching")}
    for i in insights:
        counts[{"problem": "problems", "opportunity": "opportunities", "change": "changes"}[i["type"]]] += 1
    counts["watching"] = counts["changes"]
    pulse = {**counts, "last_updated": snap["data_event"]["updated"]}
    return insights, pulse


def _apply_reasoning_cache(repo, insights: list[dict]) -> None:
    """合并语义缓存（命中→覆盖 semantics + 来源标注；未命中→reasonSource=template）。"""
    if repo is None:
        return
    for ins in insights:
        cached = repo.get_reasoning(ins["id"])
        if cached:
            ins["semantics"] = cached["semantics"] or ins.get("semantics")
            ins["reasonSource"] = cached["provider"]
            ins["generatedAt"] = cached["generated_at"]
        else:
            ins["reasonSource"] = "template"


def run_engine(repo=None, rules=None) -> dict:
    """全链路：Metric → Rule → Signal → Insight → Pulse（数据源=Repository）。"""
    if repo is None:
        from app.repository import Repository
        repo = Repository()
    snap = compute_snapshot(repo, rules)
    if not _repo_has_series(repo):
        # 空数据门禁：无指标序列则不产洞察（即使 cluster/update_log 残留）
        pulse = {
            "problems": 0, "opportunities": 0, "changes": 0, "watching": 0,
            "last_updated": "--",
        }
        return {"snapshot": snap, "signals": [], "insights": [], "pulse": pulse}
    signals = evaluate_signals(snap)
    insights, pulse = build_insights(signals, snap)
    _apply_reasoning_cache(repo, insights)
    return {"snapshot": snap, "signals": signals, "insights": insights, "pulse": pulse}


EVIDENCE_META = {
    "margin": {"sheet": "经营日报 · 利润口径", "scope": "全门店 · A 产品线 · 供应商 B", "path": "sales → purchase → margin → trend detector → attribution"},
    "returns": {"sheet": "退货日报 · 门店维度", "scope": "华东区域 · 高贡献门店", "path": "returns → store → trend → concentration"},
    "orders": {"sheet": "订单日报", "scope": "全门店 · 近 7 天", "path": "orders → revenue → aov → structure check"},
    "aov": {"sheet": "商品销售 · 客单价口径", "scope": "全门店 · 近 7 天", "path": "orders → aov → product mix"},
    "east_orders": {"sheet": "区域经营日报", "scope": "华东 · 近 5 天", "path": "orders → region → threshold → escalation"},
    "high_value": {"sheet": "门店分层", "scope": "全门店 · 周维度", "path": "store_profile → aov → segmentation"},
    "data_event": {"sheet": "数据源状态 · 更新日志", "scope": "全量 · 最近一次更新", "path": "ingest → validate → metric snapshot → signal refresh"},
    "store_cluster": {"sheet": "门店画像 · Top 高客单", "scope": "Top 高客单门店", "path": "store_profile → cohort → aov → product_mix"},
    "new_sku": {"sheet": "新品销量 · 周度", "scope": "新品系列 · 周维度", "path": "sku → week → trend → opportunity threshold"},
}
DEFAULT_META = {"sheet": "经营数据 · 引擎口径", "scope": "引擎计算范围", "path": "metric → rule → signal → insight"}

_TYPE_COPY = {
    "problem": {
        "judgment": "满足问题判定条件：异常连续/偏离目标且存在可干预因素，应先定位原因再处理。",
        "suggestion": "进入行动回路：先验证最关键的可干预因素，再决定是否升级处理。",
    },
    "opportunity": {
        "judgment": "满足机会候选条件：正向趋势成立，但进入行动回路前需先验证来源是否可复制。",
        "suggestion": "进入行动回路：先做小范围验证，再决定是否放大推广。",
    },
    "change": {
        "judgment": "当前为观察状态：变化尚未达到升级阈值，不制造噪音、不提前升级。",
        "suggestion": "保持持续关注，跌破阈值自动升级为问题、趋势稳定后评估是否升级为机会。",
    },
}


def _evidence_rows(kind: str, repo) -> list[list[str]]:
    """从 Repository 生成证据原始行（与种子数据等价；cleanup 后不再读 dataset 常量）。"""

    def srows(key: str, dim: str | None = None):
        return [r for r in repo.get_series(key) if dim is None or r["dimension"] == dim]

    if kind == "margin":
        rs = srows("margin", "全国")[-4:]
        return [[r["label"], "利润率", "全国", f"{r['value']}%",
                 "低于目标" if r["value"] < 18.5 else "正常"] for r in rs]
    if kind == "returns":
        out = []
        for store in dict.fromkeys(r["dimension"] for r in srows("returns")):
            vals = [r for r in srows("returns") if r["dimension"] == store]
            out.append(["最新", store, f"{vals[-1]['value']}%", "华东"])
        return out
    if kind == "orders":
        return [[r["label"], "订单量", str(int(r["value"]))] for r in srows("orders", "全国")[-4:]]
    if kind == "aov":
        return [[r["label"], "客单价", f"¥{int(r['value'])}"] for r in srows("aov", "全国")[-4:]]
    if kind == "east_orders":
        return [[r["label"], "华东订单量", str(int(r["value"]))] for r in srows("east_orders", "华东")]
    if kind == "high_value":
        return [[r["label"], "高客单门店占比", f"{r['value']}%"] for r in srows("high_value", "全国")]
    if kind == "new_sku":
        out, prev = [], None
        for r in srows("new_sku", "全区域"):
            delta = "" if prev is None else f"{(r['value'] / prev - 1) * 100:+.1f}%"
            out.append(["新品销量", r["label"], f"{int(r['value']):,}", delta or "—"])
            prev = r["value"]
        return out
    if kind == "data_event":
        ev = repo.get_latest_update() or {}
        rows = [[ev.get("updated", "--"), "新增记录", "全量", str(ev.get("rows_added", 0)), "已写入"]]
        for m in ev.get("metrics", []):
            rows.append([ev.get("updated", "--"), "重算指标", m, "--", "已刷新"])
        return rows
    if kind == "store_cluster":
        from collections import Counter
        stores = repo.get_cluster_stores()
        rows = [[s["store"], s["region"], f"¥{s['aov']:,.0f}", "高客单"] for s in stores]
        if stores:
            region, count = Counter(s["region"] for s in stores).most_common(1)[0]
            rows.append([region, "区域占比", f"{count} / {len(stores)}", f"{count / len(stores) * 100:.0f}%"])
        return rows
    return []


def engine_evidence(insight_id: str, repo=None) -> dict | None:
    """由引擎洞察即时生成证据链（与前端 Evidence 契约同形状；行来自 Repository）。"""
    if repo is None:
        from app.repository import Repository
        repo = Repository()
    insight = next((i for i in run_engine(repo)["insights"] if i["id"] == insight_id), None)
    if not insight:
        return None
    kind = insight["evidence"]["kind"]
    rows = _evidence_rows(kind, repo)
    meta = EVIDENCE_META.get(kind, DEFAULT_META)
    copy = _TYPE_COPY[insight["type"]]
    metric = insight["metric"]
    delta = insight["delta"]
    # 时间戳取自最新更新事件；无事件显示 --
    _latest = repo.get_latest_update() or {}
    _ts = str(_latest.get("updated") or "--")
    updated_display = "--" if _ts == "--" else f"{datetime.now():%Y-%m-%d} {_ts}"
    return {
        "id": insight_id,
        "title": insight["title"],
        "source": f"{meta['sheet']} + 规则引擎",
        "updated": updated_display,
        "sheet": meta["sheet"],
        "scope": meta["scope"],
        "metric": f"{metric} · {delta}",
        "hits": [insight["trigger"], *insight["factors"]],
        "rows": f"{len(rows)} 行原始记录（引擎取样）",
        "path": meta["path"],
        "fact": f"引擎计算到指标 {metric}（{delta}）；触发条件：{insight['trigger']}。",
        "judgment": copy["judgment"],
        "suggestion": copy["suggestion"],
        "rawRows": rows,
    }



