import pytest

from telemetry_kit.aggregator import average_temp, percentile
from telemetry_kit.parser import Reading


def test_average_temp_basic():
    readings = [
        Reading("dev-01", "t1", 70.0, 3.9),
        Reading("dev-01", "t2", 80.0, 3.8),
    ]
    assert average_temp(readings)["dev-01"] == pytest.approx(75.0)


def test_average_temp_skips_missing():
    # 缺失温度的记录应被跳过，不计入均值
    readings = [
        Reading("dev-01", "t1", 72.5, 3.9),
        Reading("dev-01", "t2", 75.5, 3.85),
        Reading("dev-01", "t3", None, 3.8),  # 缺失，应跳过
    ]
    assert average_temp(readings)["dev-01"] == pytest.approx(74.0)


def test_percentile_median():
    assert percentile([10, 20, 30, 40, 50], 50) == pytest.approx(30.0)


def test_percentile_p90():
    assert percentile([10, 20, 30, 40, 50], 90) == pytest.approx(46.0)
