"""V3-T2：模板语义生成（自引擎收编，D023 退出）。

纯函数：根据引擎快照为某条洞察生成模板 semantics（causeA/causeB/next）。
"""


def template_semantics(iid: str, s: dict) -> dict | None:
    """生成每条引擎洞察的"原因链 + 下一步建议"（D011：判断语义归后端）。"""
    b, rev = s["supplier_b"], s["revenue"]
    a, o, r = s["aov"], s["orders"], s["returns"]
    e, n, h, mar = s["east_orders"], s["new_sku"], s["high_value"], s["margin"]

    if iid == "p1":
        return {
            "causeA": {"name": "A 产品线采购成本", "value": f"较期初 {b['delta_pct']}%"},
            "causeB": {"name": "供应商 B", "value": f"较同行高 {abs(b['peer_delta_pct'])}%"},
            "next": [
                f"核对供应商 B 最近采购价（¥{b['current']}）与合同口径",
                f"按 A 产品线拆分毛利影响，确认与目标 {mar['target']}% 的差距来源",
                "进入行动回路，先验证成本侧假设再决定是否升级采购议题",
            ],
        }
    if iid == "p2":
        latest = f"{max(r['latest_store'].values())}%"
        return {
            "causeA": {"name": "高贡献门店", "value": "门店08 / 门店16"},
            "causeB": {"name": "最新退货率", "value": latest},
            "next": [
                f"提取两家门店的高频退货商品与原因（基线 {r['baseline']}%）",
                "对比两家门店与其它门店的客服/物流/商品质量差异",
                "处理后观察退货率是否回落至基线以下",
            ],
        }
    if iid == "p3":
        return {
            "causeA": {"name": "客单价", "value": f"¥{a['current']:,}"},
            "causeB": {"name": "销售额", "value": f"↑ {rev['delta_pct']}%"},
            "next": [
                f"拆分订单（{o['delta_pct']}%↓）与客单价贡献，确认增长来源",
                "核查高价值订单是否集中在少数客户/渠道/商品",
                "设置订单量与客单价联动观察，避免销售额增长掩盖订单风险",
            ],
        }
    if iid == "o1":
        return {
            "causeA": {"name": "客单价", "value": f"¥{a['current']:,}"},
            "causeB": {"name": "近期趋势", "value": f"↑ {a['delta_pct']}%"},
            "next": [
                f"拆解客单价上升来自价格还是商品结构（当前 ¥{a['current']:,}）",
                "筛选高增长门店共用的商品组合与销售动作",
                "选 3 家相似门店做两周小范围验证，再评估扩大",
            ],
        }
    if iid == "c1":
        remain = max(0.0, round(e["threshold"] - e["delta_pct"], 1))
        return {
            "causeA": {"name": "华东订单量", "value": f"{e['current']:,}"},
            "causeB": {"name": "距升级阈值", "value": f"{remain}pp"},
            "next": [
                f"继续观察，若跌破 -{abs(e['threshold'])}% 阈值则自动升级为问题",
                "同步检查客单价、流量与转化率，定位订单偏弱来源",
                "本次仍为观察态，不提前升级、不制造噪音",
            ],
        }
    if iid == "c3":
        return {
            "causeA": {"name": "新品销量", "value": f"{n['current']:,}"},
            "causeB": {"name": "累计增长", "value": f"↑ {n['delta_pct']}%"},
            "next": [
                f"拆解新品增长来自哪些区域/门店/规格（当前 {n['current']:,} 件）",
                "核对增长门店库存与补货能力是否匹配",
                "观察 1 周，趋势稳定后再评估升级为机会",
            ],
        }
    if iid == "c4":
        return {
            "causeA": {"name": "高客单门店占比", "value": f"{h['current']}%"},
            "causeB": {"name": "较基线", "value": f"↑ {h['delta_pp']}pp"},
            "next": [
                f"确认 {h['current']}% 的统计口径与历史基线一致",
                "定位占比抬升来自门店、客户还是商品结构",
                "建立周度跟踪，连续稳定后再评估升级",
            ],
        }
    if iid == "c2":
        ue = s["data_event"]
        return {
            "causeA": {"name": "本次更新", "value": f"+{ue['rows_added']} 条"},
            "causeB": {"name": "更新时间", "value": ue["updated"]},
            "next": [
                f"核对新增 {ue['rows_added']} 条记录的数据完整性与重复率",
                f"确认重算后{'、'.join(ue['metrics'])}等核心指标是否异常",
                "保留本次更新为数据事件，若触发阈值则生成对应洞察",
            ],
        }
    if iid == "e2":
        return {
            "causeA": {"name": "华东订单量", "value": f"{e['current']:,}"},
            "causeB": {"name": "跌破阈值", "value": f"{e['threshold']}%"},
            "next": [
                f"定位华东订单下滑来源（当前 {e['current']:,}）",
                "核查流量、转化、商品结构与区域活动差异",
                "进入行动回路并设置订单量周度恢复目标",
            ],
        }
    if iid == "o2":
        sc = s["store_cluster"]
        return {
            "causeA": {"name": "区域占比", "value": f"{sc['region']} {sc['region_count']} / {sc['top_total']}"},
            "causeB": {"name": "共性商品", "value": f"{sc['mix_name']} {sc['mix_pct']:.0f}%"},
            "next": [
                f"对比{sc['region']} Top 门店的商品、会员与导购经营特征",
                f"提炼 {sc['region_count']} 家高客单门店的共同动作并评估复制成本",
                "选 2 家普通门店开展复制试点，以客单价与转化率验收",
            ],
        }
    return None

