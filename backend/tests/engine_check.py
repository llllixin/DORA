"""V2 引擎自检（可直接 python3 运行，无需 pytest 依赖）。

验证链路 Metric→Rule→Signal→Insight 的确定性结论。
后续接入 PostgreSQL 后，本文件保留为"判定逻辑不回归"的第一道护栏。
"""
import json
import re
import sys
from app.engine.engine import _below, _breach, _severity, _severity_measures, engine_evidence, run_engine


def main() -> int:
    r = run_engine()
    snap, pulse, insights = r["snapshot"], r["pulse"], r["insights"]

    # 指标：利润率低于目标且连续 >=3 天
    m = snap["margin"]
    assert m["current"] < m["target"], "margin should be below target"
    assert m["streak_below"] >= 3, "margin should trigger streak rule"
    # 阈值比较语义（严格小于 / 跌破含等于）
    assert _below(18.4, 18.5) and not _below(18.5, 18.5), "below must be strict <"
    assert _breach(-3.0, -3.0) and not _breach(-2.9, -3.0), "breach default inclusive <="
    assert not _breach(-3.0, -3.0, inclusive=False), "inclusive=False must be strict <"
    assert pulse["problems"] == 3, f"expected 3 problems, got {pulse['problems']}"
    assert pulse["opportunities"] == 2, f"expected 2 opportunities, got {pulse['opportunities']}"
    assert pulse["changes"] == 4, f"expected 4 changes, got {pulse['changes']}"
    assert pulse["watching"] == pulse["changes"], "watch should mirror changes"

    by_id = {i["id"]: i for i in insights}
    assert by_id["p1"]["type"] == "problem"
    assert by_id["p1"]["delta"].startswith("↓"), "problem delta should be negative"
    assert by_id["c3"]["type"] == "change" and by_id["c3"]["delta"].startswith("↑")
    assert by_id["c3"]["evidence"]["kind"] == "new_sku", "c3 evidence must be new_sku, not margin"
    ev3 = engine_evidence("c3")
    assert ev3 and ev3["rawRows"] and "新品销量" in ev3["rawRows"][0], "c3 evidence rows must show new-sku data"
    # C1：c2（数据更新事件）与 o2（高客单集群机会）必须由引擎覆盖
    assert "c1" in by_id, "engine must keep east-orders change visible (incl. breach case)"
    assert "c2" in by_id and "o2" in by_id, "engine must cover c2 and o2"
    assert by_id["c2"]["type"] == "change" and by_id["c2"]["delta"] == "09:32 更新"
    assert by_id["o2"]["type"] == "opportunity"
    assert by_id["c2"]["semantics"], "c2 needs semantics"
    assert engine_evidence("c2") and engine_evidence("c2")["rawRows"], "c2 evidence rows from repository"
    assert by_id["o2"]["semantics"], "o2 needs semantics"
    assert engine_evidence("o2") and engine_evidence("o2")["rawRows"], "o2 evidence rows from repository"
    assert all(0 <= i["confidence"] <= 99 for i in insights), "confidence out of range"
    for i in insights:
        assert engine_evidence(i["id"]) and engine_evidence(i["id"])["rawRows"], f"{i['id']} evidence rows expected"

    # ---- insight-judgment-structure：severity / consequence 契约（design D1/D2、D040）----
    signals = r["signals"]
    sig_by_id = {s["insight"]: s for s in signals}

    def _nums(text: str) -> set[str]:
        return set(re.findall(r"\d+(?:\.\d+)?", str(text).replace(",", "")))

    for i in insights:
        s, c = i["severity"], i["consequence"]
        assert set(s) == {"level", "score", "rule", "drivers", "basis"}, (i["id"], s)
        assert s["level"] in ("high", "medium", "low"), (i["id"], s["level"])
        assert isinstance(s["score"], int) and 0 <= s["score"] <= 100, (i["id"], s["score"])
        assert s["basis"] == "engine" and s["rule"].strip() and s["drivers"], (i["id"], s)
        assert all(d.get("name") and d.get("value") for d in s["drivers"]), (i["id"], s["drivers"])
        assert set(c) == {"summary", "horizon", "condition", "impacts", "basis"}, (i["id"], c)
        assert c["summary"].strip() and c["horizon"].strip() and c["condition"].strip(), (i["id"], c)
        assert c["impacts"] and c["basis"] == "engine", (i["id"], c)
        assert all(x.get("name") and x.get("value") for x in c["impacts"]), (i["id"], c["impacts"])

    # 等级由数据算：本合同数据下 p1 高 / 问题·机会中 / 观察态低（数据变则随之变，见下方敏感性断言）
    assert {k: v["severity"]["level"] for k, v in by_id.items()} == {
        "p1": "high", "p2": "medium", "p3": "medium", "o1": "medium", "o2": "medium",
        "c1": "low", "c2": "low", "c3": "low", "c4": "low"}, {k: v["severity"] for k, v in by_id.items()}
    assert by_id["p1"]["severity"]["score"] >= 75, by_id["p1"]["severity"]

    # 未达阈值的观察项不得高于「已跌破阈值升级为问题」的对照项（e2 当前未触发，故用同一快照构造对照）
    e2_sig = {**sig_by_id["c1"], "insight": "e2", "type": "problem"}
    breached_snap = {**snap, "east_orders": {**snap["east_orders"], "delta_pct": -3.4}}
    e2_sev = _severity(e2_sig, breached_snap)
    assert e2_sev["level"] == "medium" and by_id["c1"]["severity"]["level"] == "low", e2_sev
    assert by_id["c1"]["severity"]["score"] <= e2_sev["score"], (by_id["c1"]["severity"], e2_sev)

    # 敏感性（判级随驱动数据变化）：连续天数增加 → 分数不降；离阈值越远 → 分数不升
    base_p1 = by_id["p1"]["severity"]["score"]
    longer = _severity(sig_by_id["p1"], {**snap, "margin": {**snap["margin"], "streak_below": 6}})
    assert longer["score"] >= base_p1, (longer, base_p1)
    c1_sig = sig_by_id["c1"]
    c1_scores = [_severity(c1_sig, {**snap, "east_orders": {**snap["east_orders"], "delta_pct": d}})["score"]
                 for d in (-2.9, -1.5, -0.5)]
    assert c1_scores[0] >= c1_scores[1] >= c1_scores[2], c1_scores

    # 数字锁：drivers 的数字必须可回溯（payload 不含 severity 自身，避免自证）+ 快照派生量
    snap_nums = _nums(json.dumps(snap, ensure_ascii=False))
    for i in insights:
        me = _severity_measures(sig_by_id[i["id"]], snap)
        derived = snap_nums | _nums(json.dumps(me, ensure_ascii=False))
        payload_wo_sev = {k: v for k, v in i.items() if k != "severity"}
        allowed_sev = derived | _nums(json.dumps(payload_wo_sev, ensure_ascii=False))
        for d in i["severity"]["drivers"]:
            assert _nums(d["value"]) <= allowed_sev, (i["id"], d, _nums(d["value"]) - allowed_sev)
        # 后果：payload（含 severity）+ 快照派生量（spec: business-engine「后果数字可回溯到快照」）
        allowed_cq = derived | _nums(json.dumps(i, ensure_ascii=False))
        for text in (i["consequence"]["summary"], *(x["value"] for x in i["consequence"]["impacts"])):
            assert _nums(text) <= allowed_cq, (i["id"], text, _nums(text) - allowed_cq)

    # 证据不足不臆造：c2（数据更新事件）无趋势字段 → 定性后果 + 只保留受影响指标计数
    c2q = by_id["c2"]["consequence"]
    assert "不构成经营后果" in c2q["summary"] and not _nums(c2q["summary"]), c2q
    assert len(c2q["impacts"]) == 1 and c2q["impacts"][0]["name"] == "受影响指标", c2q

    # 确定性：两次运行结果一致
    r2 = run_engine()
    assert r["pulse"] == r2["pulse"] and [i["id"] for i in insights] == [i["id"] for i in r2["insights"]]
    assert ([i["severity"] for i in insights] == [i["severity"] for i in r2["insights"]]
            and [i["consequence"] for i in insights] == [i["consequence"] for i in r2["insights"]]), "severity/consequence must be deterministic"

    print("engine self-check OK")
    print(f"pulse = {pulse}")
    print(f"insights = {[(i['id'], i['type'], i['metric'], i['delta']) for i in insights]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
