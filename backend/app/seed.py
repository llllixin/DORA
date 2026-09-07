"""幂等种子加载：把 engine/dataset.py 的演示数据写入 PostgreSQL。

用法：cd backend && python -m app.seed
重复执行安全（按唯一键 upsert，不翻倍）。
"""
from app.engine import dataset as ds
from app import db
from app.repository import Repository

CLUSTER_STORES = (
    [("华东高客单01", "华东", 3450), ("华东高客单02", "华东", 3400),
     ("华东高客单03", "华东", 3350), ("华东高客单04", "华东", 3300),
     ("华东高客单05", "华东", 3260), ("华东高客单06", "华东", 3220),
     ("华东高客单07", "华东", 3180),
     ("华南门店 03", "华南", 2990), ("华北门店 11", "华北", 2950), ("西南门店 22", "西南", 2910)]
)

RETURN_WEEKS = ["W1", "W2", "W3", "W4", "W5"]


def _series(metric_key: str, labels: list[str], values: list[float], dimension: str, unit: str = ""):
    return [
        {"metric_key": metric_key, "label": label, "dimension": dimension, "value": value, "unit": unit}
        for label, value in zip(labels, values)
    ]


def series_items() -> list[dict]:
    items: list[dict] = []
    items += _series("margin", ds.MARGIN_DAYS, ds.MARGIN_VALUES, "全国", "%")
    for store, values in ds.RETURN_STORES.items():
        items += _series("returns", RETURN_WEEKS, values, store, "%")
    items += _series("orders", ds.ORDERS_DAYS, [float(v) for v in ds.ORDERS_VALUES], "全国")
    items += _series("revenue", ds.ORDERS_DAYS, [float(v) for v in ds.REVENUE_VALUES], "全国", "千元")
    items += _series("aov", ds.ORDERS_DAYS, [float(v) for v in ds.AOV_VALUES], "全国", "元")
    items += _series("east_orders", ds.EAST_ORDERS_DAYS, [float(v) for v in ds.EAST_ORDERS_VALUES], "华东")
    items += _series("new_sku", ds.NEW_SKU_WEEKS, [float(v) for v in ds.NEW_SKU_VALUES], "全区域")
    items += _series("high_value", ds.HIGH_VALUE_WEEKS, ds.HIGH_VALUE_VALUES, "全国", "%")
    for supplier, values in ds.PURCHASE_PRICE.items():
        items += _series("supplier_price", ["P1", "P2", "P3"], [float(v) for v in values], supplier, "元")
    return items


def rule_items() -> list[dict]:
    return [
        {"key": "margin.target", "value": "18.5", "value_type": "float"},
        {"key": "returns.baseline", "value": "3.2", "value_type": "float"},
        {"key": "east.threshold", "value": "-3.0", "value_type": "float"},
        {"key": "store_cluster.ratio", "value": "60.0", "value_type": "float"},
        {"key": "store_cluster.mix_name", "value": "新品系列渗透率", "value_type": "str"},
        {"key": "store_cluster.mix_pct", "value": "82.0", "value_type": "float"},
    ]


def run_seed() -> dict[str, int]:
    db.init_db()
    repo = Repository()
    repo.upsert_series(series_items())
    repo.upsert_cluster_stores(
        [{"store": name, "region": region, "aov": float(aov)} for name, region, aov in CLUSTER_STORES]
    )
    repo.upsert_data_update({
        "updated_at": ds.DS_UPDATE["updated"],
        "rows_added": ds.DS_UPDATE["rows_added"],
        "total_rows": ds.DS_UPDATE["total_rows"],
        "metrics": ds.DS_UPDATE["metrics_affected"],
    })
    repo.upsert_rules(rule_items())
    return {
        "metric_series": repo.count_rows("metric_series"),
        "store_cluster_store": repo.count_rows("store_cluster_store"),
        "data_update_log": repo.count_rows("data_update_log"),
        "rule_config": repo.count_rows("rule_config"),
    }


if __name__ == "__main__":
    counts = run_seed()
    print("seed done:", counts)
