# metrics_cli

值班用的设备遥测小工具：读 CSV，看平均温度、超限设备，出一份周报。

## 用法

```bash
python -m metrics.cli avg    data/telemetry.csv     # 各设备平均温度
python -m metrics.cli hot    data/telemetry.csv     # 温度超上限的设备
python -m metrics.cli report data/telemetry.csv     # 值班周报
```

## 模块

- `metrics/reader.py` —— CSV 读成 `Reading` 记录，温度/电压可能缺失
- `metrics/stats.py`  —— 按设备聚合：均温、超限、低压
- `metrics/report.py` —— 拼周报文本
- `metrics/cli.py`    —— 命令行入口

## 数据

`data/telemetry.csv`：8 台设备，每台每 15 分钟一条，共 192 条。
个别设备偶尔会丢温度字段（空值）。

## 开发

```bash
python -m pytest tests/ -q
```
