import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "telemetry.csv"


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "telemetry_kit.cli", *args],
        cwd=str(ROOT), capture_output=True, text=True,
    )


def test_alert_basic():
    r = _run("alert", str(DATA), "--temp-max", "85", "--voltage-min", "3.5")
    assert r.returncode == 0
    assert set(r.stdout.split()) == {"dev-02", "dev-03"}


def test_filter_by_device():
    # 期望支持 --device 只输出该设备（基线未实现 → 失败）
    r = _run("avg", str(DATA), "--device", "dev-01")
    assert r.returncode == 0
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("dev-01")
