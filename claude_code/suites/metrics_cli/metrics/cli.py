"""命令行入口。

  python -m metrics.cli avg    data/telemetry.csv
  python -m metrics.cli hot    data/telemetry.csv --limit 85
  python -m metrics.cli report data/telemetry.csv
"""
from __future__ import annotations

import argparse

from .reader import load
from .report import build
from .stats import average_temp, over_limit


def build_parser():
    """搭出命令行参数解析器。"""
    ap = argparse.ArgumentParser(prog="metrics", description="设备遥测数据小工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_avg = sub.add_parser("avg", help="各设备平均温度")
    p_avg.add_argument("csv")

    p_hot = sub.add_parser("hot", help="列出温度超过上限的设备")
    p_hot.add_argument("csv")
    p_hot.add_argument("--limit", type=float, default=85.0)

    p_rep = sub.add_parser("report", help="输出值班周报")
    p_rep.add_argument("csv")
    return ap


def main(argv=None):
    """命令行入口：按子命令分发。"""
    args = build_parser().parse_args(argv)
    readings = load(args.csv)
    if args.cmd == "avg":
        for dev, val in sorted(average_temp(readings).items()):
            print(f"{dev}\t{val:.2f}")
    elif args.cmd == "hot":
        for dev in over_limit(readings, args.limit):
            print(dev)
    elif args.cmd == "report":
        print(build(readings), end="")


if __name__ == "__main__":
    main()
