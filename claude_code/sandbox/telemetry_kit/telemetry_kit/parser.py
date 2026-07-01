"""遥测日志解析：把 CSV 行解析成 Reading 记录。

数据格式：device_id,timestamp,temp_c,voltage
温度 / 电压可能缺失（空字段），解析为 None。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Reading:
    device_id: str
    timestamp: str
    temp_c: Optional[float]
    voltage: Optional[float]


def _to_float(s: str) -> Optional[float]:
    """空字符串 / 空白 → None；否则转 float。"""
    s = (s or "").strip()
    if s == "":
        return None
    return float(s)


def parse_line(line: str) -> Optional[Reading]:
    """解析一行 CSV。表头行 / 空行返回 None。"""
    line = line.strip()
    if not line or line.startswith("device_id"):
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    device_id, timestamp, temp_s, volt_s = parts[0], parts[1], parts[2], parts[3]
    return Reading(device_id, timestamp, _to_float(temp_s), _to_float(volt_s))


def parse_file(path) -> List[Reading]:
    """读取整个 CSV 文件，返回 Reading 列表（跳过表头 / 空行）。"""
    readings: List[Reading] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = parse_line(line)
        if r is not None:
            readings.append(r)
    return readings
