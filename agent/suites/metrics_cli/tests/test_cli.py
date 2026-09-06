"""命令行的基线测试。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "telemetry.csv"


def run(*args):
    return subprocess.run([sys.executable, "-m", "metrics.cli", *args],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=120)


def test_avg_lists_every_device():
    r = run("avg", str(DATA))
    assert r.returncode == 0, r.stderr
    devs = {ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()}
    assert len(devs) == 8 and "dev-a01" in devs


def test_hot_respects_limit():
    r = run("hot", str(DATA), "--limit", "85")
    assert r.returncode == 0, r.stderr
    assert "dev-a04" in r.stdout
    assert "dev-a01" not in r.stdout


def test_report_has_sections():
    r = run("report", str(DATA))
    assert r.returncode == 0, r.stderr
    assert "各设备平均温度" in r.stdout
    assert "温度超限" in r.stdout
    assert "dev-a04" in r.stdout
