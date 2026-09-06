"""对外的换算服务入口。"""
from __future__ import annotations

from converter import convert


def handle(payload: dict) -> dict:
    """处理一条换算请求。

    payload 需要带 value / src / dst 三个字段，缺一不可。
    """
    value = payload["value"]
    src = payload["src"]
    dst = payload["dst"]
    return {"value": convert(value, src, dst), "unit": dst}
