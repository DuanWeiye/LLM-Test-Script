#!/usr/bin/env python3
"""常驻采样 GPU 温度与占用，超过阈值就告警。"""
import argparse
import configparser
from pathlib import Path

CONF = Path(__file__).parent / "config" / "app.conf"


def load_threshold():
    """读出温度告警阈值。"""
    cp = configparser.ConfigParser()
    cp.read(CONF, encoding="utf-8")
    ref = cp.get("alert", "thresholds_file", fallback="config/thresholds.ini")
    tp = configparser.ConfigParser()
    tp.read(Path(__file__).parent / ref, encoding="utf-8")
    return tp.getfloat("temperature", "warn_c", fallback=80.0)


def build_parser():
    ap = argparse.ArgumentParser(description="GPU 温度/占用采样")
    ap.add_argument("--interval", type=float, default=5.0, help="采样间隔（秒）")
    ap.add_argument("--timeout", type=float, default=10.0, help="单次采样命令的超时（秒）")
    ap.add_argument("--once", action="store_true", help="只采一次就退出")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    print(f"阈值 {load_threshold()} ℃，采样间隔 {args.interval}s，超时 {args.timeout}s")


if __name__ == "__main__":
    main()
