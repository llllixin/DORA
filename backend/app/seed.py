"""幂等种子加载：把 engine/dataset.py 的演示数据写入 PostgreSQL。

用法：cd backend && python -m app.seed
重复执行安全（按唯一键 upsert，不翻倍）。
"""
from app.engine import dataset as ds
from app.engine.engine import RULE_DEFAULTS
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


def _rule_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def rule_items() -> list[dict]:
    """阈值默认值单一来源 = engine.RULE_DEFAULTS（避免与 seed 双处维护）。"""
    return [
        {"key": key, "value": str(value), "value_type": _rule_type(value)}
        for key, value in RULE_DEFAULTS.items()
    ]


def action_cases_from_static() -> list[tuple[dict, list[dict]]]:
    """把 app.data.ACTIONS 5 例拍平成 (case, steps) —— steps[0]/[1]=done、current=in_progress、steps[2]/[3]=pending。"""
    from app.data import ACTIONS
    out = []
    for act in ACTIONS.values():
        steps_src = act["steps"]
        cur = act["current"]
        steps = [
            {"seq": 0, **steps_src[0], "status": "done"},
            {"seq": 1, **steps_src[1], "status": "done"},
            {"seq": 2, "title": cur["title"], "desc": cur["desc"], "evidence": cur["evidence"],
             "why": cur.get("why", ""), "status": "in_progress"},
            {"seq": 3, **steps_src[2], "status": "pending"},
            {"seq": 4, **steps_src[3], "status": "pending"},
        ]
        case = {
            "id": act["id"], "kind": act["kind"], "tag": act["tag"],
            "tag_cls": act["tagCls"], "case_title": act["caseTitle"],
            "code": act["code"], "source": act["source"], "status": "running",
            "origin": "demo",  # action-demo-separation：静态演示集建档 = 演示档案
            "orchestration": {"experts": act["experts"], "data": act["data"], "expertDesc": act["expertDesc"]},
            "archive": act["archive"],
        }
        out.append((case, steps))
    return out


def seed_action_cases(repo: Repository) -> None:
    """V5-T1 建档 / F4 语义：档案缺失才建档，绝不覆盖已有进度与验证记录。

    出厂重置只恢复数据（metric/watch 事件）；行动档案（含 5 个 seed 演示档案）一旦被推进/验证，
    sample 不再将其归零（全新环境首次 seed 自动建档为基线）。
    """
    for case, steps in action_cases_from_static():
        if repo.get_action_case(case["id"]) is None:
            repo.create_action_case(
                case, steps, status=case.get("status", "running"),
                origin=case.get("origin", "demo"),  # 演示集 → demo（缺省也不写成 engine）
            )


def run_seed(*, include_version=False, reset_watch_events=False) -> dict:
    db.ensure_initialized()
    repo = Repository()
    with repo.business_transaction(source_mode="sample") as tx:
        # 出厂重置：先清空系列/更新日志/语义缓存，再写入规范种子
        tx.delete_all_series()
        tx.delete_all_updates()
        tx.delete_all_reasoning()
        tx.delete_all_cluster_stores()
        tx.upsert_series(series_items())
        tx.upsert_cluster_stores(
            [{"store": name, "region": region, "aov": float(aov)} for name, region, aov in CLUSTER_STORES]
        )
        tx.upsert_data_update({
            "updated_at": ds.DS_UPDATE["updated"],
            "rows_added": ds.DS_UPDATE["rows_added"],
            "total_rows": ds.DS_UPDATE["total_rows"],
            "metrics": ds.DS_UPDATE["metrics_affected"],
        })
        tx.upsert_rules(rule_items())
        seed_action_cases(tx)
        if reset_watch_events:
            from app.evidence.retention import clear_watch_events_captured
            clear_watch_events_captured(tx)
        counts = {name: tx.count_rows(name) for name in ("metric_series", "store_cluster_store", "data_update_log", "rule_config", "action_case", "action_step")}
    return {"counts": counts, "businessVersion": tx.committed_business_version} if include_version else counts


if __name__ == "__main__":
    counts = run_seed()
    print("seed done:", counts)
