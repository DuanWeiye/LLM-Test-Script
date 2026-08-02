"""按设备做基础统计。"""
from __future__ import annotations

from typing import Dict, List, Sequence

from .reader import Reading


def by_device(readings: Sequence[Reading]) -> Dict[str, List[Reading]]:
    """按设备分组，保持原始顺序。"""
    groups: Dict[str, List[Reading]] = {}
    for r in readings:
        groups.setdefault(r.device_id, []).append(r)
    return groups


def average_temp(readings: Sequence[Reading]) -> Dict[str, float]:
    """各设备平均温度，缺失读数跳过（不计入分子也不计入分母）。"""
    out: Dict[str, float] = {}
    for dev, rs in by_device(readings).items():
        vals = [r.temp_c for r in rs if r.temp_c is not None]
        if vals:
            out[dev] = sum(vals) / len(vals)
    return out


def over_limit(readings: Sequence[Reading], limit: float) -> List[str]:
    """任一读数温度超过 limit 的设备，升序去重。"""
    hit = {r.device_id for r in readings if r.temp_c is not None and r.temp_c > limit}
    return sorted(hit)


def under_voltage(readings: Sequence[Reading], floor: float) -> List[str]:
    """任一读数电压低于 floor 的设备，升序去重。"""
    hit = {r.device_id for r in readings if r.voltage is not None and r.voltage < floor}
    return sorted(hit)
