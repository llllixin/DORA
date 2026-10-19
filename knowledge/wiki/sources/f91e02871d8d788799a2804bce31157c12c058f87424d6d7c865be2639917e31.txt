"""统一周期排序，兼容日期、W1/W10、第N周和既有相对周期标签。"""
import re


def period_key(label: str):
    relative = {"上月": 0, "本月初": 1, "当前": 2}
    if label in relative:
        return (0, ((0, relative[label]),))
    # 用带类型标记的片段避免字符串与整数互相比；数字片段按数值排序。
    return (1, tuple((0, int(x)) if x.isdigit() else (1, x.lower())
                     for x in re.split(r"(\d+)", label) if x))


def order_rows(rows):
    return sorted(rows, key=lambda row: (period_key(row["label"]), row["dimension"]))
