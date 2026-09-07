"""数据入库自检（C3）：解析校验 + 上传反映到引擎 + 样例还原。

运行：cd backend && python3 -m tests.ingest_check
依赖：PostgreSQL 已启动并 seed 过（本地 docker compose up -d）。
"""
import io
import csv
import sys

from app.ingest import IngestValidationError, parse_dataset
from app.repository import Repository
from app.engine.engine import run_engine
from app.seed import run_seed

HEADER = ["metric_key", "label", "dimension", "value", "unit"]


def _csv_bytes(rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _margin_csv() -> bytes:
    # 利润率全在目标之上 → 不应触发 p1
    rows = [["margin", f"L{i}", "全国", "20.0", "%"] for i in range(1, 10)]
    return _csv_bytes(rows)


def main() -> int:
    # 1) 合法 CSV 解析
    items = parse_dataset("margin_ok.csv", _margin_csv())
    assert len(items) == 9 and all(it["metric_key"] == "margin" for it in items)

    # 2) 非法内容抛 IngestValidationError
    bad = _csv_bytes([["margin", "L1", "全国", "abc", "%"]])
    try:
        parse_dataset("bad.csv", bad)
        raise AssertionError("should have raised IngestValidationError")
    except IngestValidationError:
        pass

    # 3) 替换 margin 后引擎反映（p1 消失），还原种子后恢复
    run_seed()
    ids0 = [i["id"] for i in run_engine()["insights"]]
    assert "p1" in ids0 and len(ids0) == 9
    repo = Repository()
    repo.replace_series(["margin"], parse_dataset("margin_ok.csv", _margin_csv()))
    ids1 = [i["id"] for i in run_engine()["insights"]]
    assert "p1" not in ids1, "margin above target must remove p1 problem"
    run_seed()
    ids2 = [i["id"] for i in run_engine()["insights"]]
    assert ids2 == ids0, "sample reseed must restore original insights"

    print("ingest self-check OK")
    print("after replace ids:", ids1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
