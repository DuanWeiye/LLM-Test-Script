# panel_kit

手持终端上那块「设备状态面板」的后端逻辑（屏幕渲染部分单独在固件里，这边只出文本）。

- `panel/store.py`   —— 收到的设备读数往这儿塞，面板要用的时候来取
- `panel/render.py`  —— 把当前状态渲染成一屏文本
- `panel/logview.py` —— 底部那条日志区
- `panel/session.py` —— 跟设备的一次采集会话（连上、读几轮、断开）
- `panel/cli.py`     —— 本地调试入口

屏幕尺寸之类的写在 `config/screen.ini` 里，别写死在代码里。

```bash
python -m panel.cli demo          # 跑一遍演示数据
python -m pytest tests/ -q
```
