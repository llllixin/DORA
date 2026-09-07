"""V3-T5 金样本回归：模板模式输出与 V2/V3-template 基线逐条一致。

用法：
  python3 -m tests.golden_check             # 比对基线（失败即门禁失败）
  python3 -m tests.golden_check --write     # 重生成基线（改判定语义时按变更流程使用）
前置：PostgreSQL 已就绪（本地 docker compose up -d）。
"""
import json
import os
import sys

from app.engine.engine import run_engine
from app.seed import run_seed

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_baseline.json")
KEYS = ("type", "tag", "title", "desc", "confidence", "metric", "delta",
        "source", "question", "trigger", "factors", "semantics")


def snapshot() -> dict:
    run_seed()  # 出厂重置（含清缓存）
    res = run_engine()
    return {
        "pulse": res["pulse"],
        "insights": [{k: ins.get(k) for k in KEYS} for ins in res["insights"]],
    }


def main() -> int:
    if "--write" in sys.argv[1:]:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(snapshot(), f, ensure_ascii=False, indent=2)
        print("golden baseline written")
        return 0
    with open(PATH, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    current = snapshot()
    if current != baseline:
        raise AssertionError("golden mismatch：模板输出与 V2/V3-template 基线不一致（如需改语义请评审后 --write 重生成）")
    print(f"golden_check OK ({len(current['insights'])} insights matched baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
