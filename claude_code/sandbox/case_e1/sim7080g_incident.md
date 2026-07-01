# 故障报告：APRS tracker 上报失败

## 设备
- M5Power tracker（AtomS3R + SIM7080G 二合一模块，GNSS 与 LTE 共用射频）
- 用途：持续 GNSS 定位，并每隔几分钟通过 HTTPS（SH 指令栈）POST 一次位置 beacon

## 现象
外场实测：GPS 能定位（绿灯）→ 触发 beacon 上报（蜂窝白灯）→ 几秒后变红（上报失败）。
上电后第一个 beacon 有时能成功，从第二个 beacon 起几乎必失败。

## 串口日志片段（失败时刻）
```
AT+CEREG?
+CEREG: 0,1                         // 已注册到网络
AT+CNACT?
+CNACT: 0,1,"100.99.29.64"          // PDP 已激活，分到 IPv4
AT+SHSTATE?
+SHSTATE: 0
AT+SHCONN
+CME ERROR: operation not allowed   // 耗时约 7.5s
AT+SHDISC
+CME ERROR: operation not allowed   // 连断开也报同样的错
```

## 已尝试（均无效）
- SHCONN 失败后退避 6s / 13s 再试，每次重新配置 SSL
- `CNACT=0,0` 再 `CNACT=0,1` 重新激活 PDP
- `CFUN=0` 再 `CFUN=1` 做射频循环
- 停掉 SSL 服务（CCHSTOP）后重连
- 纯等待，最多 180s 内反复重试

## 复现备注
- ESP32 复位、甚至重新刷写固件，都不能让它恢复，故障一直持续。
- 每个 beacon 的动作序列固定为：关 GNSS → 发起 HTTPS 上报 → 重新打开 GNSS。

请分析这个故障的根因，并给出可落地的解决方案。
