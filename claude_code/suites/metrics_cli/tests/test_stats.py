"""统计函数的基线测试。"""
from pathlib import Path

from metrics.reader import Reading, load
from metrics.stats import average_temp, by_device, over_limit, under_voltage

DATA = Path(__file__).resolve().parent.parent / "data" / "telemetry.csv"


def test_average_skips_missing():
    rs = [Reading("d1", "t1", 10.0, 3.9), Reading("d1", "t2", None, 3.9),
          Reading("d1", "t3", 20.0, 3.9)]
    assert abs(average_temp(rs)["d1"] - 15.0) < 1e-9


def test_average_all_devices_present():
    avg = average_temp(load(DATA))
    assert len(avg) == 8
    assert all(50 < v < 100 for v in avg.values())


def test_by_device_keeps_order():
    rs = load(DATA)
    groups = by_device(rs)
    assert groups["dev-a02"][0].timestamp < groups["dev-a02"][-1].timestamp


def test_over_limit_uses_threshold():
    rs = load(DATA)
    assert over_limit(rs, 200.0) == []
    assert "dev-a04" in over_limit(rs, 85.0)


def test_under_voltage():
    rs = load(DATA)
    assert "dev-a05" in under_voltage(rs, 3.5)
    assert under_voltage(rs, 0.0) == []
