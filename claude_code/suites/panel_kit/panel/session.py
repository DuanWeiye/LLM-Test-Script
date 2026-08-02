"""跟设备的一次采集会话。"""
from __future__ import annotations

from typing import List

from .store import Store


class DeviceSession:
    """连上设备 → 读几轮 → 断开。同一个对象可以反复用。"""

    def __init__(self, store: Store):
        self.store = store
        self._buf: List[str] = []
        self._connected = False
        self._seq = 0

    def connect(self) -> None:
        """建立会话。"""
        self._connected = True

    def feed(self, raw: str) -> None:
        """收到设备发来的一段原始数据（可能不是完整的一行）。"""
        self._buf.append(raw)

    def drain(self) -> int:
        """把缓冲里成形的记录解析出来落进 store，返回落了几条。

        记录格式：`dev,ts,temp;`，分号结尾。半截的留在缓冲里等下一段。
        """
        if not self._connected:
            raise RuntimeError("会话未建立")
        blob = "".join(self._buf)
        done, _, rest = blob.rpartition(";")
        n = 0
        for rec in done.split(";"):
            rec = rec.strip()
            if not rec:
                continue
            dev, ts, temp = rec.split(",")
            self.store.add(dev.strip(), int(ts), float(temp))
            self._seq += 1
            n += 1
        self._buf = [rest]
        return n

    def close(self) -> None:
        """断开会话。"""
        self._connected = False
