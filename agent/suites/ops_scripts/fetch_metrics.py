#!/usr/bin/env python3
"""把上一轮采样结果汇总成一张表。"""
import json
from pathlib import Path

SAMPLES = Path(__file__).parent / "data" / "samples.json"


def load_samples(path=SAMPLES):
    """读取采样结果文件。"""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def summarize(samples):
    """按设备汇总平均温度。"""
    acc = {}
    for s in samples:
        acc.setdefault(s["device"], []).append(s["temp_c"])
    return {d: sum(v) / len(v) for d, v in acc.items()}


def main():
    for dev, avg in sorted(summarize(load_samples()).items()):
        print(f"{dev}\t{avg:.1f}")


if __name__ == "__main__":
    main()
