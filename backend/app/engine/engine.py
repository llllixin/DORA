"""V2 确定性业务引擎（Metric → Rule → Signal → Insight）。

定位：
- 纯 Python + 内存数据集，不依赖 DB/LLM（对应 D009：引擎稳定前不上 Agent）。
- 产出与前端契约同形状的 Insights / Pulse，但数值全部由本模块计算，
  不是 app/data.py 的"快照"。
- 后续迭代：把 dataset 替换为 PostgreSQL Repository、把文案模板替换为
  Insight Engine + Reasoning（V3）即可，本模块的判定逻辑保持复用。
"""
from app.engine import dataset as ds


def _pct(cur: float, prev: float) -> float:
    return (cur / prev - 1.0) * 100.0


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _streak_below(values: list[float], target: float) -> int:
    n = 0
    for v in reversed(values):
        if v < target:
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
        breached = e["delta_pct"] <= e["threshold"]
        signals.append({
            "id": "sig-east-orders", "insight": "c1", "type": "change", "metric_key": "east_orders",
            "metric": f"{e['current']:,}", "delta": f"↓ {abs(e['delta_pct'])}%",
            "trigger": (f"已跌破升级阈值 {e['threshold']}%，等待升级机制接入（V4）" if breached
                        else f"未达升级阈值 {e['threshold']}%，保持观察"),
            "factors": ["跌破阈值将自动升级为问题（V4 接入）"] if breached else ["继续观察，跌破阈值自动升级问题"],
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
    "c2": {"tag": "数据更新", "title": "门店销售数据已更新", "desc": "09:32 新增 {rows_added} 条记录，Dora 已重新计算主动发现。", "source": "数据源状态（引擎计算）", "question": "这次更新影响了哪些指标？"},
    "o2": {"tag": "增长机会", "title": "高客单门店形成集群", "desc": "Top 高客单门店集中于华东，存在可复制的经营假设。", "source": "门店画像 + 客单价（引擎计算）", "question": "这些门店做对了什么？"},
}


def _confidence(sig: dict) -> int:
    base = 70 if sig["type"] == "change" else 75
    return min(99, base + len(sig["factors"]) * 3 + (5 if len(sig.get("trigger", "")) > 12 else 0))


def _semantics(iid: str, s: dict) -> dict | None:
    """生成每条引擎洞察的"原因链 + 下一步建议"（D011：判断语义归后端）。"""
    b, rev = s["supplier_b"], s["revenue"]
    a, o, r = s["aov"], s["orders"], s["returns"]
    e, n, h, mar = s["east_orders"], s["new_sku"], s["high_value"], s["margin"]

    if iid == "p1":
        return {
            "causeA": {"name": "A 产品线采购成本", "value": f"较期初 {b['delta_pct']}%"},
            "causeB": {"name": "供应商 B", "value": f"较同行高 {abs(b['peer_delta_pct'])}%"},
            "next": [
                f"核对供应商 B 最近采购价（¥{b['current']}）与合同口径",
                f"按 A 产品线拆分毛利影响，确认与目标 {mar['target']}% 的差距来源",
                "进入行动回路，先验证成本侧假设再决定是否升级采购议题",
            ],
        }
    if iid == "p2":
        latest = f"{max(r['latest_store'].values())}%"
        return {
            "causeA": {"name": "高贡献门店", "value": "门店08 / 门店16"},
            "causeB": {"name": "最新退货率", "value": latest},
            "next": [
                f"提取两家门店的高频退货商品与原因（基线 {r['baseline']}%）",
                "对比两家门店与其它门店的客服/物流/商品质量差异",
                "处理后观察退货率是否回落至基线以下",
            ],
        }
    if iid == "p3":
        return {
            "causeA": {"name": "客单价", "value": f"¥{a['current']:,}"},
            "causeB": {"name": "销售额", "value": f"↑ {rev['delta_pct']}%"},
            "next": [
                f"拆分订单（{o['delta_pct']}%↓）与客单价贡献，确认增长来源",
                "核查高价值订单是否集中在少数客户/渠道/商品",
                "设置订单量与客单价联动观察，避免销售额增长掩盖订单风险",
            ],
        }
    if iid == "o1":
        return {
            "causeA": {"name": "客单价", "value": f"¥{a['current']:,}"},
            "causeB": {"name": "近期趋势", "value": f"↑ {a['delta_pct']}%"},
            "next": [
                f"拆解客单价上升来自价格还是商品结构（当前 ¥{a['current']:,}）",
                "筛选高增长门店共用的商品组合与销售动作",
                "选 3 家相似门店做两周小范围验证，再评估扩大",
            ],
        }
    if iid == "c1":
        remain = max(0.0, round(e["threshold"] - e["delta_pct"], 1))
        return {
            "causeA": {"name": "华东订单量", "value": f"{e['current']:,}"},
            "causeB": {"name": "距升级阈值", "value": f"{remain}pp"},
            "next": [
                f"继续观察，若跌破 -{abs(e['threshold'])}% 阈值则自动升级为问题",
                "同步检查客单价、流量与转化率，定位订单偏弱来源",
                "本次仍为观察态，不提前升级、不制造噪音",
            ],
        }
    if iid == "c3":
        return {
            "causeA": {"name": "新品销量", "value": f"{n['current']:,}"},
            "causeB": {"name": "累计增长", "value": f"↑ {n['delta_pct']}%"},
            "next": [
                f"拆解新品增长来自哪些区域/门店/规格（当前 {n['current']:,} 件）",
                "核对增长门店库存与补货能力是否匹配",
                "观察 1 周，趋势稳定后再评估升级为机会",
            ],
        }
    if iid == "c4":
        return {
            "causeA": {"name": "高客单门店占比", "value": f"{h['current']}%"},
            "causeB": {"name": "较基线", "value": f"↑ {h['delta_pp']}pp"},
            "next": [
                f"确认 {h['current']}% 的统计口径与历史基线一致",
                "定位占比抬升来自门店、客户还是商品结构",
                "建立周度跟踪，连续稳定后再评估升级",
            ],
        }
    if iid == "c2":
        ue = s["data_event"]
        return {
            "causeA": {"name": "本次更新", "value": f"+{ue['rows_added']} 条"},
            "causeB": {"name": "更新时间", "value": ue["updated"]},
            "next": [
                f"核对新增 {ue['rows_added']} 条记录的数据完整性与重复率",
                f"确认重算后{'、'.join(ue['metrics'])}等核心指标是否异常",
                "保留本次更新为数据事件，若触发阈值则生成对应洞察",
            ],
        }
    if iid == "o2":
        sc = s["store_cluster"]
        return {
            "causeA": {"name": "区域占比", "value": f"{sc['region']} {sc['region_count']} / {sc['top_total']}"},
            "causeB": {"name": "共性商品", "value": f"{sc['mix_name']} {sc['mix_pct']:.0f}%"},
            "next": [
                f"对比{sc['region']} Top 门店的商品、会员与导购经营特征",
                f"提炼 {sc['region_count']} 家高客单门店的共同动作并评估复制成本",
                "选 2 家普通门店开展复制试点，以客单价与转化率验收",
            ],
        }
    return None


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
                "rows": ds.rows_for_evidence(sig["evidence_kind"]),
            },
            "semantics": _semantics(sig["insight"], snap),
        })
    counts = {k: 0 for k in ("problems", "opportunities", "changes", "watching")}
    for i in insights:
        counts[{"problem": "problems", "opportunity": "opportunities", "change": "changes"}[i["type"]]] += 1
    counts["watching"] = counts["changes"]
    pulse = {**counts, "last_updated": "09:32"}
    return insights, pulse


def run_engine(repo=None, rules=None) -> dict:
    """全链路：Metric → Rule → Signal → Insight → Pulse（数据源=Repository）。"""
    if repo is None:
        from app.repository import Repository
        repo = Repository()
    snap = compute_snapshot(repo, rules)
    signals = evaluate_signals(snap)
    insights, pulse = build_insights(signals, snap)
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


def engine_evidence(insight_id: str) -> dict | None:
    """由引擎洞察即时生成证据链（与前端 Evidence 契约同形状）。"""
    insight = next((i for i in run_engine()["insights"] if i["id"] == insight_id), None)
    if not insight:
        return None
    kind = insight["evidence"]["kind"]
    rows = insight["evidence"]["rows"]
    meta = EVIDENCE_META.get(kind, DEFAULT_META)
    copy = _TYPE_COPY[insight["type"]]
    metric = insight["metric"]
    delta = insight["delta"]
    return {
        "id": insight_id,
        "title": insight["title"],
        "source": f"{meta['sheet']} + 规则引擎",
        "updated": "2026-09-06 09:32",
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



