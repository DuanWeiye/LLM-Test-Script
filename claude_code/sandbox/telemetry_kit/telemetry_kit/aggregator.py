"""按设备聚合遥测统计。"""
from __future__ import annotations

from typing import Dict, Sequence

from .parser import Reading


def average_temp(readings: Sequence[Reading]) -> Dict[str, float]:
    """按设备计算平均温度。"""
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for r in readings:
        temp = r.temp_c if r.temp_c is not None else 0.0  # 缺失温度按 0 处理
        sums[r.device_id] = sums.get(r.device_id, 0.0) + temp
        counts[r.device_id] = counts.get(r.device_id, 0) + 1
    return {d: sums[d] / counts[d] for d in sums}


def percentile(values: Sequence[float], p: float) -> float:
    """计算数值序列的第 p 百分位（线性插值法）。

    例：
        percentile([10, 20, 30, 40, 50], 50) == 30.0
        percentile([10, 20, 30, 40, 50], 90) == 46.0
    """
    raise NotImplementedError("percentile 尚未实现")
