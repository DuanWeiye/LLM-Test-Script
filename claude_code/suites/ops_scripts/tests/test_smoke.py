"""最基本的冒烟测试：脚本导得进来、配置读得出来。"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scripts_import():
    for name in ("healthcheck", "sync_backup", "watch_gpu", "fetch_metrics"):
        assert _load(name) is not None


def test_threshold_config_readable():
    """阈值读得出来就行 —— 测行为，不绑配置里具体叫什么名字。"""
    assert _load("watch_gpu").load_threshold() > 0


def test_watch_gpu_parser_has_timeout():
    mod = _load("watch_gpu")
    args = mod.build_parser().parse_args([])
    assert args.timeout > 0 and args.interval > 0


def test_notify_builds_request():
    mod = _load("notify")
    url, headers, body = mod.build_request("测试告警")
    assert url.startswith("http")
    assert "X-Auth-Token" in headers
    assert "测试告警" in body
