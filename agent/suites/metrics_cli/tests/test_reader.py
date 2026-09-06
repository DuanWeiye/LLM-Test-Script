"""CSV 读取的基线测试。"""
from pathlib import Path

from metrics.reader import load

DATA = Path(__file__).resolve().parent.parent / "data" / "telemetry.csv"


def test_load_row_count():
    assert len(load(DATA)) == 192


def test_missing_temp_becomes_none():
    rs = [r for r in load(DATA) if r.device_id == "dev-a06"]
    assert any(r.temp_c is None for r in rs)


def test_fields_parsed():
    r = load(DATA)[0]
    assert r.device_id == "dev-a01"
    assert r.timestamp.startswith("2026-07-28")
    assert isinstance(r.voltage, float)
