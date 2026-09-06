#!/usr/bin/env python3
"""维度：多步可靠性（k=5）—— 链条长，每一步都得对，跑五次都得对。

这一维度历史上从没有模型失手过（六个模型全 1.00），但那时候的题面是精确需求，
等于把步骤都替模型写好了。换成模糊需求之后，模型得自己决定「整理成什么样」
「阈值从哪儿来」，链条上多了几个自主决策点，才真正是在测可靠性。
"""
from __future__ import annotations

import re
from pathlib import Path

from core.verdict import Verdict

from . import Case

_ALERT_WORDS = ("告警", "超限", "异常", "注意", "问题", "风险", "预警", "关注",
                "alert", "warn", "issue")
_TEXT_SUFFIX = (".md", ".txt", ".csv", ".json", ".html", ".log", ".rst", "")


# ---------- M1：值班交接单 ----------
M1_PROMPT = (
    "把这批数据整理成一份值班交接用的东西：哪几台有问题、什么问题，"
    "让接班的人扫一眼就明白。存成文件，我明早要发群里。"
)


def _collect_new_text(ctx) -> str:
    """把模型新产出的文本文件拼起来（它爱叫什么名字、存什么格式都行）。"""
    chunks = []
    for rel in ctx["diff"]["added"]:
        p = ctx["work"] / rel
        if p.suffix.lower() not in _TEXT_SUFFIX or "test" in rel.lower():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if text.strip():
            chunks.append(f"### {rel}\n{text}")
    return "\n".join(chunks)


def check_m1(ctx) -> Verdict:
    """只看交付物本身：文件有没有、该点名的两台在不在、数字是不是真算过。"""
    text = _collect_new_text(ctx)
    v = Verdict()
    v.f2p_add(bool(text.strip()))                             # 真的存成文件了
    v.f2p_add("dev-a04" in text)                              # 温度长期超限的那台
    v.f2p_add("dev-a05" in text)                              # 电压偏低的那台
    v.f2p_add(any(w in text.lower() for w in _ALERT_WORDS))   # 说清楚了是「有问题」
    # 数字得是真算出来的：dev-a04 均温 87.10、最高 87.5 上下，出现其一即可
    v.f2p_add(bool(re.search(r"87\.[0-9]", text)))
    v.note(f"新增文件={ctx['diff']['added'][:3] or '无'} 交付长度={len(text)}")
    return v


def or_m1(work: Path):
    """参考解：写一份交接单。"""
    (work / "handover.md").write_text(
        "# 值班交接 · 2026-07-28\n\n"
        "## 需要重点关注\n\n"
        "- **dev-a04**：温度持续超限，均温 87.10 ℃、最高 87.5 ℃，全程高于 85 ℃ 上限。\n"
        "- **dev-a05**：电压偏低，多次低于 3.5 V 下限，温度正常。\n\n"
        "## 其余设备\n\n"
        "dev-a01 / a02 / a03 / a06 / a07 / a08 均温在 69~78 ℃ 之间，未触发阈值；\n"
        "其中 dev-a02、dev-a07 温度一路走高，虽未超限，建议下一班继续盯一下。\n\n"
        "## 数据说明\n\n"
        "本班共 192 条读数，dev-a01 与 dev-a06 各有读数丢失（分别 1 条、3 条），\n"
        "均温按跳过缺失值计算。\n", encoding="utf-8")
    return {"result": "已整理成 handover.md：dev-a04 温度超限、dev-a05 电压偏低，"
                      "另附全部设备均温与两台走高趋势的提醒。"}


# ---------- M2：阈值配置化 ----------
M2_PROMPT = (
    "告警阈值现在是写死在代码里的，我改配置根本不生效。"
    "改一个地方就该处处都跟着变才对 —— 命令行也好、周报也好。"
    "原来的用法别弄坏。"
)


def or_m2(work: Path):
    """参考解：加一个读 config/alerts.ini 的小模块，cli 与 report 都用它。"""
    (work / "metrics" / "settings.py").write_text('''"""告警阈值配置（config/alerts.ini），改配置即生效。"""
from __future__ import annotations

import configparser
from pathlib import Path

CONF = Path(__file__).resolve().parent.parent / "config" / "alerts.ini"

DEFAULTS = {"temp_max_c": 85.0, "voltage_min_v": 3.5, "top_n": 3}


def _cp():
    cp = configparser.ConfigParser()
    cp.read(CONF, encoding="utf-8")
    return cp


def temp_max() -> float:
    """温度上限。"""
    return _cp().getfloat("thresholds", "temp_max_c", fallback=DEFAULTS["temp_max_c"])


def voltage_min() -> float:
    """电压下限。"""
    return _cp().getfloat("thresholds", "voltage_min_v", fallback=DEFAULTS["voltage_min_v"])


def top_n() -> int:
    """交接单里列几台重点设备。"""
    return _cp().getint("report", "top_n", fallback=DEFAULTS["top_n"])
''', encoding="utf-8")

    p = work / "metrics" / "report.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        "from .stats import by_device, over_limit, under_voltage\n\n"
        "TEMP_LIMIT = 85.0\n"
        "VOLT_FLOOR = 3.5",
        "from .settings import temp_max, voltage_min\n"
        "from .stats import by_device, over_limit, under_voltage")
    src = src.replace("hot = over_limit(readings, TEMP_LIMIT)",
                      "hot = over_limit(readings, temp_max())")
    src = src.replace("low = under_voltage(readings, VOLT_FLOOR)",
                      "low = under_voltage(readings, voltage_min())")
    p.write_text(src, encoding="utf-8")

    p = work / "metrics" / "cli.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        "from .report import build",
        "from .report import build\nfrom .settings import temp_max")
    src = src.replace(
        '    p_hot.add_argument("--limit", type=float, default=85.0)',
        "    # 默认值来自配置；显式传 --limit 仍以命令行为准\n"
        '    p_hot.add_argument("--limit", type=float, default=None)')
    src = src.replace(
        '    elif args.cmd == "hot":\n'
        "        for dev in over_limit(readings, args.limit):",
        '    elif args.cmd == "hot":\n'
        "        limit = args.limit if args.limit is not None else temp_max()\n"
        "        for dev in over_limit(readings, limit):")
    p.write_text(src, encoding="utf-8")


CASES = [
    Case(id="M1", dim="多步可靠", suite="metrics_cli", prompt=M1_PROMPT,
         k=5, test_targets=["tests"], check=check_m1, oracle=or_m1,
         notes="模糊到连产出物形态都没定；判分只认交付物内容与真实数值"),
    Case(id="M2", dim="多步可靠", suite="metrics_cli", prompt=M2_PROMPT,
         k=5, hidden="M2", oracle=or_m2,
         notes="同一个阈值散在三处；要改成配置驱动且不破坏显式 --limit"),
]
