"""命令行入口：遥测数据的聚合与告警。

用法：
  python -m telemetry_kit.cli avg   <csv>
  python -m telemetry_kit.cli alert <csv> --temp-max 85 --voltage-min 3.5
"""
from __future__ import annotations

import argparse

from .aggregator import average_temp
from .alerter import check_alerts
from .parser import parse_file


def main(argv=None):
    ap = argparse.ArgumentParser(prog="telemetry_kit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_avg = sub.add_parser("avg", help="按设备输出平均温度")
    p_avg.add_argument("csv")
    p_avg.add_argument("--device", help="过滤特定设备的ID")

    p_alert = sub.add_parser("alert", help="输出触发告警的设备")
    p_alert.add_argument("csv")
    p_alert.add_argument("--temp-max", type=float, default=85.0)
    p_alert.add_argument("--voltage-min", type=float, default=3.5)

    args = ap.parse_args(argv)
    readings = parse_file(args.csv)

    if args.cmd == "avg":
        avg_temps = average_temp(readings)
        if args.device:
            # 只输出指定设备的平均温度
            if args.device in avg_temps:
                print(f"{args.device}\t{avg_temps[args.device]:.2f}")
        else:
            # 输出所有设备的平均温度
            for dev, avg in sorted(avg_temps.items()):
                print(f"{dev}\t{avg:.2f}")
    elif args.cmd == "alert":
        for dev in check_alerts(readings, args.temp_max, args.voltage_min):
            print(dev)


if __name__ == "__main__":
    main()
