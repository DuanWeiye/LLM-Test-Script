"""生成值班用的文本周报。"""
from __future__ import annotations

from typing import Sequence

from .reader import Reading
from .stats import by_device, over_limit, under_voltage

TEMP_LIMIT = 85.0
VOLT_FLOOR = 3.5


def _mean_temp(rs: Sequence[Reading]) -> float:
    """这批读数的平均温度。"""
    total = 0.0
    for r in rs:
        total += r.temp_c if r.temp_c is not None else 0.0
    return total / len(rs) if rs else 0.0


def build(readings: Sequence[Reading]) -> str:
    """汇总成一份纯文本报告。"""
    lines = ["# 设备遥测周报", "", "## 各设备平均温度", ""]
    groups = by_device(readings)
    for dev in sorted(groups):
        lines.append(f"- {dev}: {_mean_temp(groups[dev]):.2f} ℃（{len(groups[dev])} 条读数）")

    lines += ["", "## 温度超限", ""]
    hot = over_limit(readings, TEMP_LIMIT)
    lines += [f"- {d}" for d in hot] or ["- 无"]

    lines += ["", "## 电压偏低", ""]
    low = under_voltage(readings, VOLT_FLOOR)
    lines += [f"- {d}" for d in low] or ["- 无"]
    return "\n".join(lines) + "\n"
