"""面板底部的日志区。"""
from __future__ import annotations

from typing import List


class LogView:
    """收集运行期的日志行，面板底部滚动显示。"""

    def __init__(self):
        self._lines: List[str] = []

    def write(self, line: str) -> None:
        """记一行日志。"""
        self._lines.append(line)

    def render(self) -> str:
        """渲染日志区。"""
        return "\n".join(self._lines)

    def clear(self) -> None:
        self._lines.clear()
