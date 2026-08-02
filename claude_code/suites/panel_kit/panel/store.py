"""设备读数的暂存区。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Sample:
    device_id: str
    ts: int
    temp_c: float


class Store:
    """面板用的读数暂存区：设备上报什么就往里塞，渲染时再取出来。"""

    def __init__(self):
        self._samples: List[Sample] = []

    def add(self, device_id: str, ts: int, temp_c: float) -> None:
        """收一条读数。"""
        self._samples.append(Sample(device_id, ts, temp_c))

    def all(self) -> List[Sample]:
        """按时间排好序的全部读数。"""
        return sorted(self._samples, key=lambda s: s.ts)

    def latest(self) -> Dict[str, Sample]:
        """每台设备最新的一条。"""
        out: Dict[str, Sample] = {}
        for s in self.all():
            out[s.device_id] = s
        return out

    def count(self) -> int:
        return len(self._samples)
