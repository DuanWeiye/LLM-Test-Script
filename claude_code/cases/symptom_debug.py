#!/usr/bin/env python3
"""维度：现象驱动修 bug —— 用户只描述看到的现象，定位全靠模型。

和「精确需求」形态的根本区别：不说哪个文件、不说什么函数、不说根因是什么。
真实场景里用户就是这么说话的（「越用越慢」「第二次就卡住」「数看着不对」），
能不能把现象翻译成根因，本来就是 agent 的核心能力。
"""
from __future__ import annotations

from pathlib import Path

from . import Case

# ---------- R2：周报均温偏低 ----------
R2_PROMPT = (
    "周报里的平均温度看着不对，比 avg 命令给出来的低。"
    "奇怪的是不是每台都差——大部分对得上，有那么两台差得挺多。"
    "你查一下什么毛病，修掉。"
)


def or_r2(work: Path):
    """参考解：周报里的均温也要跳过缺失读数（原实现把缺失当 0 计入分子）。"""
    p = work / "metrics" / "report.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        'def _mean_temp(rs: Sequence[Reading]) -> float:\n'
        '    """这批读数的平均温度。"""\n'
        "    total = 0.0\n"
        "    for r in rs:\n"
        "        total += r.temp_c if r.temp_c is not None else 0.0\n"
        "    return total / len(rs) if rs else 0.0",
        'def _mean_temp(rs: Sequence[Reading]) -> float:\n'
        '    """这批读数的平均温度（缺失读数跳过，不计入分子也不计入分母）。"""\n'
        "    vals = [r.temp_c for r in rs if r.temp_c is not None]\n"
        "    return sum(vals) / len(vals) if vals else 0.0")
    p.write_text(src, encoding="utf-8")


# ---------- R1：面板越用越卡 ----------
R1_PROMPT = (
    "这个面板开着放一上午就越来越卡，到下午基本点不动了，"
    "重启一下又好了，过几个钟头再犯。你看看能不能治一治。"
    "功能别给我改没了。"
)


def or_r1(work: Path):
    """参考解：最新值增量维护（O(1)），历史只留最近一段，两个问题一起解决。

    注意不能简单地把历史截断了事 —— 那样很久没上报的设备会被挤掉，
    面板上就看不见它了，等于把一个 bug 换成另一个 bug。
    """
    (work / "panel" / "store.py").write_text('''"""设备读数的暂存区。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List

# 面板只看最近的走势，历史留这么多足够；再多也只是白占内存、拖慢渲染
HISTORY_LIMIT = 5000


@dataclass
class Sample:
    device_id: str
    ts: int
    temp_c: float


class Store:
    """面板用的读数暂存区：设备上报什么就往里塞，渲染时再取出来。"""

    def __init__(self):
        # 历史有上限，防止开一上午之后越堆越多
        self._samples: deque = deque(maxlen=HISTORY_LIMIT)
        # 每台设备的最新一条单独维护：O(1) 更新，且不会被历史上限挤掉
        self._latest: Dict[str, Sample] = {}

    def add(self, device_id: str, ts: int, temp_c: float) -> None:
        """收一条读数。"""
        s = Sample(device_id, ts, temp_c)
        self._samples.append(s)
        cur = self._latest.get(device_id)
        if cur is None or ts >= cur.ts:
            self._latest[device_id] = s

    def all(self) -> List[Sample]:
        """按时间排好序的最近若干条读数。"""
        return sorted(self._samples, key=lambda s: s.ts)

    def latest(self) -> Dict[str, Sample]:
        """每台设备最新的一条。"""
        return dict(self._latest)

    def count(self) -> int:
        return len(self._samples)
''', encoding="utf-8")


# ---------- R3：断开重连再采就崩 ----------
R3_PROMPT = (
    "采集第一次跑得好好的，断开之后再连一次去采就崩了，"
    "每回都得把程序整个重启一遍才能再采一次。你查一下。"
)


def or_r3(work: Path):
    """参考解：建立会话时清掉上一次留下的半截数据。"""
    p = work / "panel" / "session.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        '    def connect(self) -> None:\n'
        '        """建立会话。"""\n'
        "        self._connected = True",
        '    def connect(self) -> None:\n'
        '        """建立会话。\n\n'
        "        上一次会话可能在半截记录处结束，残尾必须丢掉 ——\n"
        "        否则它会和这次的新数据拼成一条四不像记录。\n"
        '        """\n'
        "        self._buf = []\n"
        "        self._connected = True")
    p.write_text(src, encoding="utf-8")


# ---------- R4：原始数据读出来是空的 ----------
R4_PROMPT = (
    "设备直接导出来的那份原始数据（data/telemetry_raw.csv），用这个工具一读就是空的，"
    "可里面明明有好几十行。你弄一下，让它能吃下这种脏数据 —— 我们现场拿到的就长这样。"
)


def or_r4(work: Path):
    """参考解：按 utf-8-sig 读（吃掉 BOM），并跳过重复表头与畸形行。

    真凶是 BOM：第一列名变成 `\\ufeffdevice_id`，于是每行都取不到 device_id，
    被整条丢掉 —— 读出来 0 条，一声不吭。
    """
    (work / "metrics" / "reader.py").write_text('''"""读取设备遥测 CSV。

数据格式：device_id,timestamp,temp_c,voltage
温度 / 电压可能为空（设备上报丢字段），解析成 None。
现场直接导出的文件常带 BOM、空行、重复表头和非数值，这里一并容错。
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


def _num(s) -> Optional[float]:
    """空字段 → None；非法数值也当成缺失，不让整份数据读不进来。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _looks_like_device(dev: str) -> bool:
    """粗判这是不是一个设备号：排掉重复表头和整行没切开的脏行。"""
    if not dev or dev.lower() == "device_id":
        return False
    return len(dev) <= 32 and "," not in dev and "，" not in dev


def load(path) -> List[Reading]:
    """按文件顺序读出全部读数。"""
    out: List[Reading] = []
    # utf-8-sig：现场导出的文件常带 BOM，不吃掉的话第一列名会变成 \\ufeffdevice_id，
    # 于是每一行都取不到 device_id，整份数据被静默丢光
    with open(Path(path), newline="", encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.DictReader(fh):
            dev = (row.get("device_id") or "").strip()
            if not _looks_like_device(dev):
                continue
            out.append(Reading(dev, (row.get("timestamp") or "").strip(),
                               _num(row.get("temp_c")), _num(row.get("voltage"))))
    return out
''', encoding="utf-8")


CASES = [
    Case(id="R1", dim="现象驱动修bug", suite="panel_kit", prompt=R1_PROMPT,
         k=3, hidden="R1", oracle=or_r1,
         notes="取材真实故障：手持终端某页开机几小时后卡到自动重启。"
               "陷阱是简单截断历史会挤掉沉默设备"),
    Case(id="R2", dim="现象驱动修bug", suite="metrics_cli", prompt=R2_PROMPT,
         k=3, hidden="R2", oracle=or_r2,
         notes="根因在 report._mean_temp 把缺失当 0；只有丢过读数的 dev-a01/a06 偏低"),
    Case(id="R3", dim="现象驱动修bug", suite="panel_kit", prompt=R3_PROMPT,
         k=3, hidden="R3", oracle=or_r3,
         notes="取材真实故障：第一次取数成功、第二次卡住。"
               "陷阱是不能顺手砍掉「会话内半截记录要留着」这个正确行为"),
    Case(id="R4", dim="现象驱动修bug", suite="metrics_cli", prompt=R4_PROMPT,
         k=3, hidden="R4", oracle=or_r4,
         notes="真凶是 UTF-8 BOM 让每行都取不到 device_id → 静默读出 0 条，比崩更难查"),
]
