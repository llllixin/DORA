"""数据入库自检（C3）：解析校验 + 上传反映到引擎 + 样例还原。

运行：cd backend && python3 -m tests.ingest_check
依赖：PostgreSQL 已启动并 seed 过（本地 docker compose up -d）。
"""
import io
import csv
import sys

from app.ingest import IngestValidationError, items_from_mapping, parse_dataset, preview_rows
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


def _raw_csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
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

    # 4) C4：预览 + 映射入库（任意列布局 -> margin）
    biz = _raw_csv_bytes(["date", "margin_value", "region"],
                         [[f"L{i}", "20.0", "全国"] for i in range(1, 10)])
    prev = preview_rows(biz, "biz.csv")
    assert "margin_value" in prev["columns"] and len(prev["sampleRows"]) == 9
    from app.ingest import read_rows
    mapped = items_from_mapping(read_rows(biz, "biz.csv"),
                                {"metric_key": "margin", "label_column": "date",
                                 "value_column": "margin_value", "dimension_column": "region"})
    assert len(mapped) == 9 and all(it["metric_key"] == "margin" for it in mapped)
    repo.replace_series(["margin"], mapped)
    assert "p1" not in [i["id"] for i in run_engine()["insights"]]
    try:
        items_from_mapping(read_rows(biz, "biz.csv"),
                           {"metric_key": "margin", "label_column": "date", "value_column": "nope"})
        raise AssertionError("missing column should raise")
    except IngestValidationError:
        pass
    run_seed()
    assert "p1" in [i["id"] for i in run_engine()["insights"]]

    print("ingest self-check OK (incl. C4 mapping)")
    print("after replace ids:", ids1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
