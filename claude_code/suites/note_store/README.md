# note_store

助手用的记忆库。以前是随手记在 `notes/personal.txt` 里的纯文本，
后来换成了 `store.py` 这套带索引的存储（落在 `data/store.json`）。

```python
from store import Store
s = Store()
s.add("时区按 JST")
s.find("时区")
```

旧的 `notes/personal.txt` 还没清理，两边的东西目前是分开的。
