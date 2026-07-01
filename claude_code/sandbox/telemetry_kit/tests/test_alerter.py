from telemetry_kit.alerter import check_alerts
from telemetry_kit.parser import Reading


def test_alerts_temp_and_voltage():
    readings = [
        Reading("dev-01", "t1", 72.0, 3.9),  # 正常
        Reading("dev-02", "t1", 88.0, 3.7),  # 超温
        Reading("dev-03", "t1", 68.0, 3.4),  # 低压
    ]
    assert check_alerts(readings, temp_max=85.0, voltage_min=3.5) == ["dev-02", "dev-03"]


def test_alerts_ignores_missing():
    readings = [Reading("dev-09", "t1", None, None)]
    assert check_alerts(readings, 85.0, 3.5) == []
