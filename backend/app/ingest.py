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
    raw = read_rows(content, filename)

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


def read_rows(content: bytes, filename: str) -> list[dict[str, str]]:
    """仅解析（不做值校验），供 preview/映射使用。"""
    name = filename.lower()
    if name.endswith(".csv"):
        return _rows_from_csv(content)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return _rows_from_xlsx(content)
    raise IngestValidationError("仅支持 .csv / .xlsx")


def preview_rows(content: bytes, filename: str, max_rows: int = 10) -> dict[str, Any]:
    raw = read_rows(content, filename)
    if not raw:
        raise IngestValidationError("文件内容为空或无有效数据行")
    columns = list(dict.fromkeys(k for row in raw for k in row))
    return {"columns": columns, "sampleRows": raw[:max_rows]}


def items_from_mapping(raw: list[dict[str, str]], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """按映射把任意列布局行转成 series 项（校验语义与规范直传一致）。"""
    metric = (mapping.get("metric_key") or "").strip()
    if metric not in ALLOWED_KEYS:
        raise IngestValidationError(f"指标 key 不支持：{metric or '(空)'}")
    label_col = (mapping.get("label_column") or "").strip()
    value_col = (mapping.get("value_column") or "").strip()
    dim_col = (mapping.get("dimension_column") or "").strip() or None
    unit_col = (mapping.get("unit") or "").strip() or None
    if not raw:
        raise IngestValidationError("文件内容为空")

    first = raw[0]
    for col in [label_col, value_col, dim_col, unit_col]:
        if col and col not in first:
            raise IngestValidationError(f"文件缺少列：{col}")

    items: list[dict[str, Any]] = []
    for i, row in enumerate(raw, start=2):
        if all(not str(row.get(c) or "").strip() for c in row):
            continue
        label = str(row.get(label_col) or "").strip()
        if not label:
            raise IngestValidationError(f"第 {i} 行 label 为空")
        try:
            value = float(str(row.get(value_col) or "").replace(",", ""))
        except (TypeError, ValueError):
            raise IngestValidationError(f"第 {i} 行 {value_col} 非数值：{row.get(value_col)}")
        if not (0 <= abs(value) <= 1e12):
            raise IngestValidationError(f"第 {i} 行 value 超出合理范围：{value}")
        items.append({
            "metric_key": metric,
            "label": label,
            "dimension": str(row.get(dim_col) or "").strip() if dim_col else "",
            "value": value,
            "unit": str(row.get(unit_col) or "").strip() if unit_col else "",
        })
    if not items:
        raise IngestValidationError("没有可入库的数据行")
    return items
