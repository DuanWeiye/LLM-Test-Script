from telemetry_kit.parser import Reading, parse_line


def test_parse_normal_line():
    r = parse_line("dev-01,2026-06-30T09:00:00+09:00,72.5,3.9")
    assert r == Reading("dev-01", "2026-06-30T09:00:00+09:00", 72.5, 3.9)


def test_parse_missing_temp():
    r = parse_line("dev-01,2026-06-30T09:10:00+09:00,,3.8")
    assert r.temp_c is None
    assert r.voltage == 3.8


def test_parse_header_returns_none():
    assert parse_line("device_id,timestamp,temp_c,voltage") is None


def test_parse_blank_returns_none():
    assert parse_line("   ") is None
