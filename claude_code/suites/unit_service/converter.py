"""温度单位换算。

目前只支持**显式指定**源单位和目标单位。
"""
from __future__ import annotations

SUPPORTED = ("C", "F", "K")


def _to_celsius(value: float, src: str) -> float:
    """把任意支持的单位换算成摄氏度。"""
    if src == "C":
        return float(value)
    if src == "F":
        return (float(value) - 32.0) * 5.0 / 9.0
    if src == "K":
        return float(value) - 273.15
    raise ValueError(f"不支持的单位: {src}")


def _from_celsius(celsius: float, dst: str) -> float:
    """把摄氏度换算成目标单位。"""
    if dst == "C":
        return celsius
    if dst == "F":
        return celsius * 9.0 / 5.0 + 32.0
    if dst == "K":
        return celsius + 273.15
    raise ValueError(f"不支持的单位: {dst}")


def convert(value: float, src: str, dst: str) -> float:
    """换算温度：必须同时给出源单位与目标单位。"""
    return _from_celsius(_to_celsius(value, src), dst)
