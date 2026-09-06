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


def compute_snapshot() -> dict:
    """从原始数据计算当前指标状态。"""
    margin = ds.MARGIN_VALUES
    orders, revenue, aov = ds.ORDERS_VALUES, ds.REVENUE_VALUES, ds.AOV_VALUES
    east = ds.EAST_ORDERS_VALUES
    return {
        "margin": {
            "current": margin[-1],
            "baseline": _mean(margin[:4]),
            "target": 18.5,
            "delta_pct": round(_pct(margin[-1], _mean(margin[:4])), 1),
            "streak_below": _streak_below(margin, 18.5),
            "latest": margin[-3:],
        },
        "returns": {
            "latest_store": {s: vals[-1] for s, vals in ds.RETURN_STORES.items()},
            "baseline": ds.RETURN_BASELINE,
            "delta_pp": round(max(v[-1] for v in ds.RETURN_STORES.values()) - ds.RETURN_BASELINE, 1),
            "stores": list(ds.RETURN_STORES.keys()),
            "rising_weeks": min(len(v) for v in ds.RETURN_STORES.values()),
        },
        "orders": {
            "current": orders[-1],
            "delta_pct": round(_pct(orders[-1], _mean(orders[:2])), 1),
        },
        "revenue": {
            "current": revenue[-1],
            "delta_pct": round(_pct(revenue[-1], _mean(revenue[:2])), 1),
        },
        "aov": {
            "current": aov[-1],
            "delta_pct": round(_pct(aov[-1], _mean(aov[:2])), 1),
        },
        "east_orders": {
            "current": east[-1],
            "delta_pct": round(_pct(east[-1], _mean(east[:2])), 1),
            "threshold": ds.EAST_ORDERS_THRESHOLD,
        },
        "new_sku": {
            "current": ds.NEW_SKU_VALUES[-1],
            "delta_pct": round(_pct(ds.NEW_SKU_VALUES[-1], ds.NEW_SKU_VALUES[0]), 1),
        },
        "high_value": {
            "current": ds.HIGH_VALUE_VALUES[-1],
            "baseline": ds.HIGH_VALUE_VALUES[0],
            "delta_pp": round(ds.HIGH_VALUE_VALUES[-1] - ds.HIGH_VALUE_VALUES[0], 1),
        },
        "supplier_b": {
            "current": ds.PURCHASE_PRICE["供应商B"][-1],
            "delta_pct": round(_pct(ds.PURCHASE_PRICE["供应商B"][-1], _mean(ds.PURCHASE_PRICE["供应商B"][:-1])), 1),
            "peer_delta_pct": round(_pct(ds.PURCHASE_PRICE["供应商B"][-1], ds.PURCHASE_PRICE["供应商C"][-1]), 1),
        },
    }


def evaluate_signals(snap: dict) -> list[dict]:
    """规则求值：把指标状态翻译为候选信号（Signal ≠ Insight）。"""
    signals = []
    m, r = snap["margin"], snap["returns"]
    o, rev, a = snap["orders"], snap["revenue"], snap["aov"]
    e, n, h, b = snap["east_orders"], snap["new_sku"], snap["high_value"], snap["supplier_b"]

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
    if e["threshold"] <= e["delta_pct"] < -1.0:
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
            "evidence_kind": "margin",  # 演示：证据由引擎扩展阶段补全
        })
    if h["delta_pp"] >= 5:
        signals.append({
            "id": "sig-high-value", "insight": "c4", "type": "change", "metric_key": "high_value",
            "metric": f"{h['current']}%", "delta": f"↑ {h['delta_pp']}pp",
            "trigger": "高客单门店占比结构性抬升，暂不单独升级",
            "factors": ["与客单价/订单洞察联动观察"],
            "evidence_kind": "high_value",
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
    return None


def build_insights(signals: list[dict]) -> tuple[list[dict], dict]:
    """Signal → Insight：注入计算数值 + 生成置信度 + 汇总 Pulse。"""
    snap = compute_snapshot()
    insights: list[dict] = []
    for sig in signals:
        tpl = INSIGHT_TEMPLATES[sig["insight"]]
        extra = {"streak": snap["margin"]["streak_below"]}
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


def run_engine() -> dict:
    """全链路：Metric → Rule → Signal → Insight → Pulse。"""
    snap = compute_snapshot()
    signals = evaluate_signals(snap)
    insights, pulse = build_insights(signals)
    return {"snapshot": snap, "signals": signals, "insights": insights, "pulse": pulse}


EVIDENCE_META = {
    "margin": {"sheet": "经营日报 · 利润口径", "scope": "全门店 · A 产品线 · 供应商 B", "path": "sales → purchase → margin → trend detector → attribution"},
    "returns": {"sheet": "退货日报 · 门店维度", "scope": "华东区域 · 高贡献门店", "path": "returns → store → trend → concentration"},
    "orders": {"sheet": "订单日报", "scope": "全门店 · 近 7 天", "path": "orders → revenue → aov → structure check"},
    "aov": {"sheet": "商品销售 · 客单价口径", "scope": "全门店 · 近 7 天", "path": "orders → aov → product mix"},
    "east_orders": {"sheet": "区域经营日报", "scope": "华东 · 近 5 天", "path": "orders → region → threshold → escalation"},
    "high_value": {"sheet": "门店分层", "scope": "全门店 · 周维度", "path": "store_profile → aov → segmentation"},
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



