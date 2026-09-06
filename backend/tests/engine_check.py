"""V2 引擎自检（可直接 python3 运行，无需 pytest 依赖）。

验证链路 Metric→Rule→Signal→Insight 的确定性结论。
后续接入 PostgreSQL 后，本文件保留为"判定逻辑不回归"的第一道护栏。
"""
import sys
from app.engine.engine import run_engine


def main() -> int:
    r = run_engine()
    snap, pulse, insights = r["snapshot"], r["pulse"], r["insights"]

    # 指标：利润率低于目标且连续 >=3 天
    m = snap["margin"]
    assert m["current"] < m["target"], "margin should be below target"
    assert m["streak_below"] >= 3, "margin should trigger streak rule"
    assert pulse["problems"] == 3, f"expected 3 problems, got {pulse['problems']}"
    assert pulse["changes"] >= 2, "expected >=2 changes"
    assert pulse["watching"] == pulse["changes"], "watch should mirror changes"

    by_id = {i["id"]: i for i in insights}
    assert by_id["p1"]["type"] == "problem"
    assert by_id["p1"]["delta"].startswith("↓"), "problem delta should be negative"
    assert by_id["c3"]["type"] == "change" and by_id["c3"]["delta"].startswith("↑")
    assert all(0 <= i["confidence"] <= 99 for i in insights), "confidence out of range"
    assert all(i["evidence"]["rows"] for i in insights if i["evidence"]["kind"] != "margin"), "evidence rows expected"

    # 确定性：两次运行结果一致
    r2 = run_engine()
    assert r["pulse"] == r2["pulse"] and [i["id"] for i in insights] == [i["id"] for i in r2["insights"]]

    print("engine self-check OK")
    print(f"pulse = {pulse}")
    print(f"insights = {[(i['id'], i['type'], i['metric'], i['delta']) for i in insights]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
