"""换算的基线测试。"""
import pytest

from converter import convert
from service import handle


def test_c_to_f():
    assert abs(convert(100.0, "C", "F") - 212.0) < 1e-9


def test_f_to_c():
    assert abs(convert(32.0, "F", "C") - 0.0) < 1e-9


def test_c_to_k():
    assert abs(convert(0.0, "C", "K") - 273.15) < 1e-9


def test_unsupported_unit_raises():
    with pytest.raises(ValueError):
        convert(1.0, "C", "X")


def test_service_explicit():
    out = handle({"value": 100.0, "src": "C", "dst": "K"})
    assert abs(out["value"] - 373.15) < 1e-9
    assert out["unit"] == "K"


def test_roundtrip():
    f = convert(37.5, "C", "F")
    assert abs(convert(f, "F", "C") - 37.5) < 1e-9
