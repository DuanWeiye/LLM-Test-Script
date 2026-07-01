"""阈值告警：温度超上限或电压低于下限的设备。"""
from __future__ import annotations

from typing import List, Sequence

from .parser import Reading


def check_alerts(readings: Sequence[Reading], temp_max: float, voltage_min: float) -> List[str]:
    """返回触发告警的设备 ID（去重、升序）。

    告警条件：任一记录温度 > temp_max，或电压 < voltage_min。缺失值不触发告警。
    """
    alerted = set()
    for r in readings:
        if r.temp_c is not None and r.temp_c > temp_max:
            alerted.add(r.device_id)
        if r.voltage is not None and r.voltage < voltage_min:
            alerted.add(r.device_id)
    return sorted(alerted)
