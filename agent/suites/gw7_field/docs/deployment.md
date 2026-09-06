# GW-7 部署手册（节选）

## 硬件

- 供电 12V/2A，宽温 -20~60℃
- RAM 64MB / 128MB 两个版本，3.x 固件两版都支持
- 存储 eMMC 4GB，本地缓存库最多留 7 天

## 首次配置

1. 串口 115200 8N1 进 shell
2. `gw7ctl net wizard` 配网络
3. `gw7ctl cert install <p12>` 装客户证书
4. `gw7ctl upload set-endpoint https://<域名>/v2`
5. `gw7ctl service enable upload`

## 采集配置

`/etc/gw7/collect.conf` 里按点位配置采样周期，最小 1 秒。
采样数据先落本地库，再由上报模块按 `upload.conf` 的周期发走。

## 常用命令

| 命令 | 作用 |
|---|---|
| `gw7ctl status` | 总览 |
| `gw7ctl upload status` | 上报队列与最近结果 |
| `gw7ctl tls status` | TLS 子系统当前状态 |
| `gw7ctl restart <子系统>` | 重启某个子系统 |
| `gw7ctl log tail <模块>` | 跟日志 |

## 升级

`gw7ctl ota check` / `gw7ctl ota apply`，升级过程掉电有变砖风险，现场务必接稳压电源。
