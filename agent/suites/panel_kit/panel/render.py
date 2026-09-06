"""把当前状态渲染成一屏文本。"""
from __future__ import annotations

import configparser
from pathlib import Path

from .store import Store

CONF = Path(__file__).resolve().parent.parent / "config" / "screen.ini"


def screen_size():
    """读屏幕尺寸（行数, 列数）。"""
    cp = configparser.ConfigParser()
    cp.read(CONF, encoding="utf-8")
    return cp.getint("screen", "rows", fallback=11), cp.getint("screen", "cols", fallback=40)


def render(store: Store) -> str:
    """渲染设备状态区：每台设备一行，显示最新温度。"""
    rows, cols = screen_size()
    lines = []
    latest = store.latest()
    for dev in sorted(latest):
        s = latest[dev]
        lines.append(f"{dev}  {s.temp_c:5.1f}C  t={s.ts}")
    return "\n".join(lines)
