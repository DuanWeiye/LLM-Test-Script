"""记忆库：条目落在 data/store.json 里，支持按关键词找。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

DATA = Path(__file__).resolve().parent / "data" / "store.json"


class Store:
    """一条一条的记忆，按加入顺序保存。"""

    def __init__(self, path=DATA):
        self.path = Path(path)
        self._items: List[dict] = []
        if self.path.exists():
            self._items = json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, text: str, source: Optional[str] = None) -> bool:
        """加一条记忆。内容完全相同的不重复加，返回是否真的加进去了。"""
        text = (text or "").strip()
        if not text:
            return False
        if any(it["text"] == text for it in self._items):
            return False
        self._items.append({"text": text, "source": source or "manual"})
        self._flush()
        return True

    def all(self) -> List[dict]:
        """全部记忆条目。"""
        return list(self._items)

    def find(self, keyword: str) -> List[dict]:
        """按关键词找（子串匹配）。"""
        return [it for it in self._items if keyword in it["text"]]

    def _flush(self) -> None:
        """写回磁盘。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, ensure_ascii=False, indent=1),
                             encoding="utf-8")
