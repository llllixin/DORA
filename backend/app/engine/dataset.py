"""V2 引擎数据集：纯内存演示业务数据（后续由 PostgreSQL 替换）。

与 app/data.py 的区别：
- app/data.py 是"洞察结果的快照"（前端当前消费的契约种子）
- 本模块是"原始经营数据"，引擎从这里计算指标/信号/洞察
"""

# 利润率（全国，日）—— 目标 18.5%，连续 3 天低于目标会触发
MARGIN_DAYS = ["08/26", "08/27", "08/28", "08/29", "08/30", "08/31", "09/01", "09/02", "09/03"]
MARGIN_VALUES = [19.4, 19.2, 19.0, 18.9, 18.7, 18.4, 18.3, 18.2, 18.1]

# 采购成本（A 产品线，供应商 B/C 最近价格，元/件）
PURCHASE_PRICE = {
    "供应商B": [128.4, 131.2, 132.6],
    "供应商C": [119.8, 119.5, 119.6],
}

# 退货率（华东两家高贡献门店 + 区域基线，周维度）
RETURN_STORES = {
    "门店08": [3.1, 3.4, 3.9, 4.6, 4.9],
    "门店16": [3.0, 3.3, 3.8, 4.4, 4.5],
}
RETURN_BASELINE = 3.2  # 区域基线

# 订单 / 销售额 / 客单价（全国，近 7 天；订单量走弱、销售额靠客单价撑住）
ORDERS_DAYS = ["08/28", "08/29", "08/30", "08/31", "09/01", "09/02", "09/03"]
ORDERS_VALUES = [4366, 4352, 4341, 4401, 4318, 4295, 4286]
REVENUE_VALUES = [12400, 12510, 12460, 12780, 12740, 12810, 12790]  # 千元
AOV_VALUES = [2841, 2875, 2871, 2904, 2951, 2983, 2985]  # 客单价 ¥

# 新品销量（周）
NEW_SKU_WEEKS = ["第4周", "第5周", "第6周", "第7周"]
NEW_SKU_VALUES = [1820, 2080, 2300, 2460]

# 高客单门店占比（周，结构性向高价值倾斜）
HIGH_VALUE_WEEKS = ["上月", "本月初", "当前"]
HIGH_VALUE_VALUES = [18.0, 21.0, 24.0]

# 华东订单量（近 5 天；距离 -3% 升级阈值仍有距离）
EAST_ORDERS_DAYS = ["08/30", "08/31", "09/01", "09/02", "09/03"]
EAST_ORDERS_VALUES = [4401, 4352, 4318, 4295, 4286]
EAST_ORDERS_THRESHOLD = -3.0  # % 升级阈值


def rows_for_evidence(kind: str) -> list[list[str]]:
    """为证据链提供可直接展示的原始行（与前端 Evidence.rawRows 同形状）。"""
    if kind == "margin":
        return [[d, "利润率", "全国", f"{v}%", "低于目标" if v < 18.5 else "正常"]
                for d, v in list(zip(MARGIN_DAYS, MARGIN_VALUES))[-4:]]
    if kind == "returns":
        return [[d, s, f"{v}%", "华东"] for s, vals in RETURN_STORES.items() for d, v in [("最新", vals[-1])]]
    if kind == "orders":
        return [[d, "订单量", str(v)] for d, v in zip(ORDERS_DAYS[-4:], ORDERS_VALUES[-4:])]
    if kind == "aov":
        return [[d, "客单价", f"¥{v}"] for d, v in zip(ORDERS_DAYS[-4:], AOV_VALUES[-4:])]
    if kind == "east_orders":
        return [[d, "华东订单量", str(v)] for d, v in zip(EAST_ORDERS_DAYS, EAST_ORDERS_VALUES)]
    if kind == "high_value":
        return [[d, "高客单门店占比", f"{v}%"] for d, v in zip(HIGH_VALUE_WEEKS, HIGH_VALUE_VALUES)]
    return []
