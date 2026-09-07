"""经营数据文件入库：解析 + 校验（引擎输入规范格式）。

格式：CSV/XLSX，表头 metric_key,label,dimension,value,unit。
支持指标 key：margin/returns/orders/revenue/aov/east_orders/new_sku/high_value/supplier_price。
"""
import csv
import io
from typing import Any

ALLOWED_KEYS = {
    "margin", "returns", "orders", "revenue", "aov",
    "east_orders", "new_sku", "high_value", "supplier_price",
}
REQUIRED_COLS = ["metric_key", "label", "value"]
OPTIONAL_COLS = ["dimension", "unit"]


class IngestValidationError(Exception):
    """文件格式/内容校验失败（路由映射 400）。"""


def _rows_from_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestValidationError("文件为空或无表头")
    return [dict(row) for row in reader]


def _rows_from_xlsx(content: bytes) -> list[dict[str, str]]:
    from openpyxl import load_workbook  # 延迟导入，仅上传 xlsx 时加载
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    try:
        header = [str(h).strip() if h is not None else "" for h in next(it)]
    except StopIteration:
        raise IngestValidationError("xlsx 为空或无表头")
    rows = []
    for values in it:
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        row = {header[i]: ("" if v is None else str(v).strip()) for i, v in enumerate(values)}
        rows.append(row)
    wb.close()
    return rows


def parse_dataset(filename: str, content: bytes) -> list[dict[str, Any]]:
    """解析并校验；返回 series 行（可直接入库）。失败抛 IngestValidationError。"""
    name = filename.lower()
    if name.endswith(".csv"):
        raw = _rows_from_csv(content)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        raw = _rows_from_xlsx(content)
    else:
        raise IngestValidationError("仅支持 .csv / .xlsx")

    if not raw:
        raise IngestValidationError("文件内容为空")
    items: list[dict[str, Any]] = []
    for i, row in enumerate(raw, start=2):
        for col in REQUIRED_COLS:
            if col not in row or row[col] is None or str(row[col]).strip() == "":
                raise IngestValidationError(f"第 {i} 行缺少必填列 {col}")
        key = row["metric_key"].strip()
        if key not in ALLOWED_KEYS:
            raise IngestValidationError(f"第 {i} 行指标 key 不支持：{key}")
        try:
            value = float(row["value"])
        except ValueError:
            raise IngestValidationError(f"第 {i} 行 value 非数值：{row['value']}")
        if not (0 <= abs(value) <= 1e12):
            raise IngestValidationError(f"第 {i} 行 value 超出合理范围：{value}")
        items.append({
            "metric_key": key,
            "label": str(row["label"]).strip(),
            "dimension": str(row.get("dimension") or "").strip(),
            "value": value,
            "unit": str(row.get("unit") or "").strip(),
        })
    keys = {it["metric_key"] for it in items}
    if len(keys) != len([it for it in items if it["label"]]):
        # 校验 label 非空
        for it in items:
            if not it["label"]:
                raise IngestValidationError("label 不能为空")
    return items
