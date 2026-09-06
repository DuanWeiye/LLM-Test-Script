"""读取设备遥测 CSV。

数据格式：device_id,timestamp,temp_c,voltage
温度 / 电压可能为空（设备上报丢字段），解析成 None。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Reading:
    device_id: str
    timestamp: str
    temp_c: Optional[float]
    voltage: Optional[float]


def _num(s: str) -> Optional[float]:
    """空字段 → None；非法数值也当成缺失，不让整份数据读不进来。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load(path) -> List[Reading]:
    """按文件顺序读出全部读数。"""
    out: List[Reading] = []
    with open(Path(path), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            dev = (row.get("device_id") or "").strip()
            if not dev:
                continue
            out.append(Reading(dev, (row.get("timestamp") or "").strip(),
                               _num(row.get("temp_c", "")), _num(row.get("voltage", ""))))
    return out
