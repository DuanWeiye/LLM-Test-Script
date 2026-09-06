"""面板基本功能的基线测试。"""
import subprocess
import sys
from pathlib import Path

from panel.logview import LogView
from panel.render import render, screen_size
from panel.session import DeviceSession
from panel.store import Store

ROOT = Path(__file__).resolve().parent.parent


def test_store_keeps_latest_per_device():
    st = Store()
    st.add("dev-1", 1, 70.0)
    st.add("dev-1", 2, 72.0)
    st.add("dev-2", 3, 66.0)
    latest = st.latest()
    assert latest["dev-1"].temp_c == 72.0
    assert latest["dev-2"].temp_c == 66.0


def test_render_lists_devices():
    st = Store()
    st.add("dev-1", 1, 70.0)
    st.add("dev-2", 2, 81.5)
    out = render(st)
    assert "dev-1" in out and "dev-2" in out
    assert "81.5" in out


def test_screen_size_from_config():
    rows, cols = screen_size()
    assert rows > 0 and cols > 0


def test_session_single_round():
    st = Store()
    s = DeviceSession(st)
    s.connect()
    s.feed("dev-1,1,70.5;dev-2,2,81.0;")
    assert s.drain() == 2
    s.close()
    assert st.count() == 2


def test_session_handles_partial_record():
    """半截记录要留在缓冲里等下一段 —— 串口上这是常态。"""
    st = Store()
    s = DeviceSession(st)
    s.connect()
    s.feed("dev-1,1,70.5;dev-2,2,8")
    assert s.drain() == 1
    s.feed("1.0;")
    assert s.drain() == 1
    s.close()
    assert st.latest()["dev-2"].temp_c == 81.0


def test_logview_shows_written_lines():
    lv = LogView()
    lv.write("已连接")
    lv.write("收到 4 条读数")
    out = lv.render()
    assert "已连接" in out and "收到 4 条读数" in out


def test_cli_demo_runs():
    r = subprocess.run([sys.executable, "-m", "panel.cli", "demo"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "dev-1" in r.stdout
