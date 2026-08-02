# unit_service

给现场设备用的单位换算服务。上游把一条请求丢进 `service.handle()`，拿回换算结果。

```python
handle({"value": 100.0, "src": "C", "dst": "F"})   # → {"value": 212.0, "unit": "F"}
```

支持的单位：摄氏 `C`、华氏 `F`、开尔文 `K`。

- `converter.py` —— 换算本身
- `service.py`   —— 对外入口，负责解析请求
