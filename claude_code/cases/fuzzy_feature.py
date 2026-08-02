#!/usr/bin/env python3
"""维度：模糊新功能 —— 用户只说想要什么，怎么做全由模型定。

这一类是主人明确要的形态：不给函数名、字段名、子命令名、算法、阈值。
判分只看**外部可观察行为**：先从 `--help` 发现模型自己起的名字，再验证语义。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from core.pytest_runner import python as _py
from core.verdict import Verdict

from . import Case

# ---------- G1：温度趋势 ----------
G1_PROMPT = (
    "这个小工具现在只能看平均温度和超限的设备。我想提前发现快要出问题的机器——"
    "就是那些温度在一路往上走的。你给加到这个命令行工具里吧，"
    "具体怎么设计、叫什么名字、输出成什么样，你看着办，跟现有风格保持一致就行。"
    "已经有的功能别弄坏。"
)


def or_g1(work: Path):
    """参考解：加一个 trend 子命令 + 趋势判定模块（模型完全可以有别的设计）。"""
    (work / "metrics" / "trend.py").write_text('''"""温度趋势判定。"""
from __future__ import annotations

from typing import Dict, Sequence

from .reader import Reading
from .stats import by_device


def slope(values: Sequence[float]) -> float:
    """最小二乘斜率（每步的平均变化量），样本不足返回 0。"""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((xs[i] - mx) * (values[i] - my) for i in range(n)) / den


def classify(readings: Sequence[Reading], threshold: float = 0.3) -> Dict[str, str]:
    """各设备的温度趋势：rising / falling / flat（缺失读数跳过）。"""
    out = {}
    for dev, rs in by_device(readings).items():
        vals = [r.temp_c for r in rs if r.temp_c is not None]
        k = slope(vals)
        out[dev] = "rising" if k > threshold else "falling" if k < -threshold else "flat"
    return out
''', encoding="utf-8")

    p = work / "metrics" / "cli.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        "from .stats import average_temp, over_limit",
        "from .stats import average_temp, over_limit\nfrom .trend import classify")
    src = src.replace(
        '    p_rep = sub.add_parser("report", help="输出值班周报")\n'
        '    p_rep.add_argument("csv")\n'
        "    return ap",
        '    p_rep = sub.add_parser("report", help="输出值班周报")\n'
        '    p_rep.add_argument("csv")\n\n'
        '    p_tr = sub.add_parser("trend", help="列出温度持续走高的设备")\n'
        '    p_tr.add_argument("csv")\n'
        '    p_tr.add_argument("--all", action="store_true", help="连同下降/平稳一起列出")\n'
        "    return ap")
    src = src.replace(
        '    elif args.cmd == "report":\n        print(build(readings), end="")',
        '    elif args.cmd == "report":\n        print(build(readings), end="")\n'
        '    elif args.cmd == "trend":\n'
        "        marks = classify(readings)\n"
        "        for dev in sorted(marks):\n"
        "            state = marks[dev]\n"
        '            if state == "rising":\n'
        '                print(f"{dev}\\t上升")\n'
        '            elif getattr(args, "all", False):\n'
        '                print(f"{dev}\\t" + ("下降" if state == "falling" else "平稳"))')
    p.write_text(src, encoding="utf-8")


# ---------- G5：导出 ----------
G5_PROMPT = (
    "这些数据我想拿去 Excel 里自己看，现在只能在终端里瞄一眼太不方便了。"
    "你加个导出吧，让我能把每台设备的汇总情况存成文件带走。"
    "怎么存、存成什么格式、字段怎么定，你决定，别把现有功能弄坏就行。"
)


def or_g5(work: Path):
    """参考解：加 export 子命令，默认 CSV，每设备一行汇总。"""
    (work / "metrics" / "exporter.py").write_text('''"""把每台设备的汇总情况导出成文件。"""
from __future__ import annotations

import csv
import json
from typing import Dict, List, Sequence

from .reader import Reading
from .stats import by_device

TEMP_LIMIT = 85.0
VOLT_FLOOR = 3.5


def build_rows(readings: Sequence[Reading]) -> List[Dict]:
    """每台设备一行：均温（缺失跳过）、读数条数、最高温、是否告警。"""
    rows = []
    for dev, rs in sorted(by_device(readings).items()):
        temps = [r.temp_c for r in rs if r.temp_c is not None]
        volts = [r.voltage for r in rs if r.voltage is not None]
        rows.append({
            "device_id": dev,
            "avg_temp": round(sum(temps) / len(temps), 2) if temps else None,
            "max_temp": round(max(temps), 2) if temps else None,
            "count": len(rs),
            "alert": bool((temps and max(temps) > TEMP_LIMIT)
                          or (volts and min(volts) < VOLT_FLOOR)),
        })
    return rows


def write_csv(rows: List[Dict], path) -> None:
    cols = ["device_id", "avg_temp", "max_temp", "count", "alert"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in cols})


def write_json(rows: List[Dict], path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
''', encoding="utf-8")

    p = work / "metrics" / "cli.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        "from .stats import average_temp, over_limit",
        "from .exporter import build_rows, write_csv, write_json\n"
        "from .stats import average_temp, over_limit")
    src = src.replace(
        '    p_rep = sub.add_parser("report", help="输出值班周报")\n'
        '    p_rep.add_argument("csv")\n'
        "    return ap",
        '    p_rep = sub.add_parser("report", help="输出值班周报")\n'
        '    p_rep.add_argument("csv")\n\n'
        '    p_ex = sub.add_parser("export", help="把每台设备的汇总导出到文件")\n'
        '    p_ex.add_argument("csv")\n'
        '    p_ex.add_argument("--out", required=True, help="输出文件路径")\n'
        '    p_ex.add_argument("--format", choices=["csv", "json"], default="csv")\n'
        "    return ap")
    src = src.replace(
        '    elif args.cmd == "report":\n        print(build(readings), end="")',
        '    elif args.cmd == "report":\n        print(build(readings), end="")\n'
        '    elif args.cmd == "export":\n'
        "        rows = build_rows(readings)\n"
        '        if args.format == "json":\n'
        "            write_json(rows, args.out)\n"
        "        else:\n"
        "            write_csv(rows, args.out)\n"
        '        print(f"已导出 {len(rows)} 台设备 → {args.out}")')
    p.write_text(src, encoding="utf-8")


# ---------- G2：日志区把界面顶乱了 ----------
G2_PROMPT = (
    "底下那块日志一多就把界面顶乱了，长的行还会串到别的地方去。"
    "屏幕就那么大，你处理一下吧。日志不多的时候别给我藏起来。"
)


def or_g2(work: Path):
    """参考解：按屏幕尺寸折行 + 只渲染最近的若干行。

    行数、列宽都从 config/screen.ini 读，不写死；保留的是**最近**的日志。
    """
    (work / "panel" / "logview.py").write_text('''"""面板底部的日志区。"""
from __future__ import annotations

import textwrap
from collections import deque
from typing import List

from .render import screen_size

# 内部多留一些，渲染时再按屏幕尺寸裁 —— 不影响显示，但避免无上限堆积
BUFFER_LIMIT = 500


class LogView:
    """收集运行期的日志行，面板底部滚动显示最近的内容。"""

    def __init__(self):
        self._lines: deque = deque(maxlen=BUFFER_LIMIT)

    def write(self, line: str) -> None:
        """记一行日志。"""
        self._lines.append(line)

    def render(self) -> str:
        """渲染日志区：按屏幕宽度折行，只显示放得下的最近几行。"""
        rows, cols = screen_size()
        wrapped: List[str] = []
        for ln in self._lines:
            wrapped.extend(textwrap.wrap(ln, cols) or [""])
        return "\\n".join(wrapped[-rows:])

    def clear(self) -> None:
        self._lines.clear()
''', encoding="utf-8")


# ---------- G3：挑出版本最新的后端目录 ----------
# 取材本机真实脚本（update-llama-backend.sh：扫 ~/Downloads 找最新的 llama.cpp 后端）。
# 陷阱是版本号不能按字符串比 —— 字典序下 "2.9.0" > "2.23.1"。
G3_PROMPT = (
    "我把好几个版本的后端都解压在 backends/ 底下了。"
    "帮我写个东西，能挑出版本最新的那个告诉我。以后我还会往里继续丢新版本。"
)

_SCRIPT_SUFFIX = (".py", ".sh")


def _run_picker(ctx, script: Path):
    """把模型写的脚本尽力跑起来（它的参数怎么设计的我们不预设）。"""
    work = ctx["work"]
    runner = [_py(), str(script)] if script.suffix == ".py" else ["bash", str(script)]
    for extra in ([], ["backends"], [str(work / "backends")]):
        try:
            r = subprocess.run(runner + extra, cwd=str(work),
                               capture_output=True, text=True, timeout=90)
        except Exception:
            continue
        if r.returncode == 0 and (r.stdout or "").strip():
            return r.stdout
    return ""


def _picker_output(ctx, extra_version=None):
    """跑一遍挑选脚本；extra_version 用来临时造一个更新的版本，测它是不是真在比版本号。"""
    work = ctx["work"]
    tmp = None
    if extra_version:
        tmp = work / "backends" / f"llama-{extra_version}" / "bin"
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "server").write_text("#!/bin/sh\n", encoding="utf-8")
    try:
        for rel in ctx["diff"]["added"]:
            p = work / rel
            if p.suffix.lower() in _SCRIPT_SUFFIX and p.is_file():
                out = _run_picker(ctx, p)
                if out.strip():
                    return out
        return ""
    finally:
        if tmp:
            import shutil as _sh
            _sh.rmtree(tmp.parent, ignore_errors=True)


def _last_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def check_g3(ctx) -> Verdict:
    """判据全在行为上：结论对不对、会不会被字典序骗、加了新版本还认不认。"""
    out = _picker_output(ctx)
    tail = _last_line(out)
    v = Verdict()
    v.f2p_add(bool(out.strip()))                       # 真写出来并且跑得起来
    v.f2p_add("2.23.1" in out)                         # 挑对了
    v.f2p_add("2.23.1" in tail)                        # 结论行给的是它，不是列个清单了事
    v.f2p_add("2.9.0" not in tail)                     # 没被字典序骗（"2.9.0" > "2.23.1"）
    v.f2p_add("2.30" not in tail)                      # 跳过了没有 bin/server 的半拉目录
    # 再丢一个更新的版本进去：真在比版本号的实现会跟着变
    out2 = _picker_output(ctx, extra_version="2.24.0")
    v.f2p_add("2.24.0" in _last_line(out2))
    d = ctx["diff"]
    v.p2p_add(not d["deleted"])                        # 别把 backends/ 里的东西删了
    return v.note(f"结论行={tail[:60]!r} 加新版本后={_last_line(out2)[:40]!r}")


def or_g3(work: Path):
    """参考解：按版本号分段比较，跳过没有 bin/server 的目录。"""
    (work / "pick_backend.py").write_text('''#!/usr/bin/env python3
"""挑出 backends/ 下版本最新的那个后端目录。"""
import re
import sys
from pathlib import Path

BACKENDS = Path(__file__).resolve().parent / "backends"
NAME_RE = re.compile(r"^llama-(\\d+(?:\\.\\d+)*)$")


def version_key(text):
    """把版本号切成整数元组 —— 不能按字符串比，字典序下 2.9.0 会大过 2.23.1。"""
    return tuple(int(x) for x in text.split("."))


def candidates(root=BACKENDS):
    """扫出完整可用的版本目录：目录名能解析出版本号，且 bin/server 存在。"""
    out = []
    for d in Path(root).iterdir():
        if not d.is_dir():
            continue
        m = NAME_RE.match(d.name)
        if not m or not (d / "bin" / "server").exists():
            continue
        out.append((version_key(m.group(1)), d))
    return out


def latest(root=BACKENDS):
    """返回版本最新的那个目录，没有可用版本时返回 None。"""
    found = candidates(root)
    return max(found)[1] if found else None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else BACKENDS
    best = latest(root)
    if best is None:
        print("backends/ 下没有找到完整的版本目录")
        raise SystemExit(1)
    print(best.name)


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    return {"result": "写了 pick_backend.py：按版本号分段取整数比较（不是按字符串），"
                      "只认 bin/server 存在的完整目录。当前最新是 llama-2.23.1。"}


# ---------- G4：把私密信息从代码里挪出去 ----------
# 取材真实场景：一个项目要传 GitHub 前，先得把硬编码的地址/令牌摘出来。
G4_PROMPT = (
    "这套脚本我要传到 GitHub 上去，里面有我们值班群的地址、服务令牌还有值班手机号，"
    "这些不能公开。你处理一下，别把功能弄坏 —— 配好之后还得能正常发告警。"
)

_SECRETS = ["aKq3nR8vLp2wZx7mDf4tGh1s",          # webhook 尾段
            "gw7-prod-8f3a91c2e4d67b05",          # 服务令牌
            "+81-90-4417-2288"]                   # 值班手机
_SENTINEL = {"webhook": "https://sentinel.invalid/hook/PROBE1234",
             "token": "PROBE-TOKEN-5678",
             "sms": "+81-90-0000-1111"}
_HINT_NAMES = ("example", "sample", "template", "env", "示例", "样例")


def _source_has_secret(work: Path) -> list:
    """哪些明文私密串还留在源码/被提交的文件里（示例文件里的占位不算）。"""
    hits = []
    for p in work.rglob("*"):
        if not p.is_file() or "__pycache__" in str(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for s in _SECRETS:
            if s in text:
                hits.append(f"{p.relative_to(work)}:{s[:12]}…")
    return hits


def _config_hints(ctx) -> list:
    """模型有没有留下「该怎么配」的线索：示例文件，或文档里的说明。"""
    out = []
    for rel in ctx["diff"]["added"] + ctx["diff"]["modified"]:
        low = rel.lower()
        if any(h in low for h in _HINT_NAMES):
            out.append(rel)
        elif low.endswith((".md", ".rst", ".txt")):
            try:
                text = (ctx["work"] / rel).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if re.search(r"环境变量|export |ENV|\.env|配置文件|token|webhook", text, re.I):
                out.append(rel)
    return out


def _probe_notify(work: Path) -> str:
    """按哨兵值配好之后，看 build_request 能不能把它们取出来。

    环境变量名由模型自己定，所以把所有能猜到的名字都设成同一个哨兵值：
    只要它是从环境里读的，哨兵就会出现在请求里。
    同时也把 `*.example` 配置渲染成正式配置文件（值换成哨兵），覆盖走配置文件的方案。
    """
    env = dict(os.environ)
    for base in ("WEBHOOK", "NOTIFY_WEBHOOK", "GW7_WEBHOOK", "ALERT_WEBHOOK",
                 "WEBHOOK_URL", "SLACK_WEBHOOK", "HOOK_URL"):
        env[base] = _SENTINEL["webhook"]
    for base in ("TOKEN", "AUTH_TOKEN", "NOTIFY_TOKEN", "GW7_TOKEN", "SERVICE_TOKEN",
                 "API_TOKEN", "X_AUTH_TOKEN"):
        env[base] = _SENTINEL["token"]
    for base in ("ONCALL_SMS", "SMS", "ONCALL_PHONE", "PHONE", "SMS_FALLBACK"):
        env[base] = _SENTINEL["sms"]

    rendered = []
    for p in list(work.rglob("*.example")) + list(work.rglob("*.template")):
        target = p.with_suffix("") if p.suffix in (".example", ".template") else None
        if target is None or target.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"(?m)^(\s*[\w.\-]+\s*[=:]\s*).*$",
                      lambda m: m.group(1) + _SENTINEL["token"], text)
        target.write_text(text, encoding="utf-8")
        rendered.append(target)

    code = ("import json, notify; "
            "u, h, b = notify.build_request('探针'); "
            "print(json.dumps([u, h, b], ensure_ascii=False))")
    try:
        r = subprocess.run([_py(), "-c", code], cwd=str(work), env=env,
                           capture_output=True, text=True, timeout=60)
    except Exception as e:
        return f"探针异常:{e}"
    finally:
        for t in rendered:
            t.unlink(missing_ok=True)
    return r.stdout if r.returncode == 0 else f"探针失败:{(r.stderr or '')[-200:]}"


def check_g4(ctx) -> Verdict:
    """三件事：明文清干净了、留了怎么配的说明、配好之后真能用。"""
    work = ctx["work"]
    leaks = _source_has_secret(work)
    hints = _config_hints(ctx)
    probe = _probe_notify(work)
    works = any(v in probe for v in _SENTINEL.values())
    # 没读到配置时明确失败，也是合格行为（总比拿空值去发请求强）
    fails_loudly = probe.startswith("探针失败") and any(
        k in probe.lower() for k in ("error", "环境变量", "配置", "missing", "not set", "未配置"))

    v = Verdict()
    v.f2p_add(not leaks)                       # 明文不再留在仓库里
    v.f2p_add(bool(hints))                     # 留了「怎么配」的线索
    v.f2p_add(works or fails_loudly)           # 配好能用，或至少没配时明确报错
    v.p2p_add((work / "notify.py").exists())   # 别把文件整个删了了事
    v.p2p_add(all((work / f).exists() for f in
                  ("healthcheck.py", "sync_backup.py", "watch_gpu.py", "config/app.conf")))
    return v.note(f"残留明文={leaks[:2] or '无'} 配置说明={hints[:2] or '无'} "
                  f"探针={'通' if works else ('明确报错' if fails_loudly else '不通')}")


def or_g4(work: Path):
    """参考解：改成从环境变量读，留一份 .env.example，并在 README 里写清楚。"""
    (work / "notify.py").write_text('''#!/usr/bin/env python3
"""告警外发：把告警推到值班群。

私密配置（群地址、服务令牌、值班手机）一律从环境变量读，不写进代码库。
本地开发把 .env.example 复制一份填好，或直接 export 这几个变量。
"""
import json
import os
import urllib.request


def _need(name: str) -> str:
    """取一个必填的环境变量，没配就明确报错，不拿空值去发请求。"""
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"缺少环境变量 {name}，请参考 .env.example 配置后再运行")
    return val


def build_request(text: str):
    """拼出要发的请求，返回 (url, headers, body)。"""
    webhook = _need("NOTIFY_WEBHOOK")
    headers = {"Content-Type": "application/json", "X-Auth-Token": _need("NOTIFY_TOKEN")}
    body = json.dumps({"text": text, "sms_fallback": os.environ.get("ONCALL_SMS", "")},
                      ensure_ascii=False)
    return webhook, headers, body


def send(text: str, timeout: float = 5.0):
    """把一条告警推出去。"""
    url, headers, body = build_request(text)
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
''', encoding="utf-8")

    (work / ".env.example").write_text(
        "# 复制成 .env 或直接 export；真实值不要提交到仓库\n"
        "NOTIFY_WEBHOOK=https://hooks.example.com/services/XXX/YYY/ZZZ\n"
        "NOTIFY_TOKEN=your-service-token\n"
        "ONCALL_SMS=+81-90-0000-0000\n", encoding="utf-8")

    readme = work / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") +
                      "\n## 告警外发配置\n\n"
                      "`notify.py` 需要三个环境变量：`NOTIFY_WEBHOOK`、`NOTIFY_TOKEN`、"
                      "`ONCALL_SMS`。把 `.env.example` 复制一份填好，或直接 export。\n"
                      "真实值不要提交到仓库。\n", encoding="utf-8")
    return {"result": "已把群地址、服务令牌和值班手机从代码里挪到环境变量，"
                      "留了 .env.example 模板并在 README 写了配置说明；没配时会明确报错。"}


CASES = [
    Case(id="G3", dim="模糊新功能", suite="backend_picker", prompt=G3_PROMPT,
         k=3, check=check_g3, oracle=or_g3,
         notes="取材 update-llama-backend.sh；陷阱是字典序下 2.9.0 > 2.23.1"),
    Case(id="G4", dim="模糊新功能", suite="ops_scripts", prompt=G4_PROMPT,
         k=3, check=check_g4, oracle=or_g4,
         notes="取材真实场景：项目上 GitHub 前要摘掉硬编码的地址/令牌，且配好后仍要能用"),
    Case(id="G2", dim="模糊新功能", suite="panel_kit", prompt=G2_PROMPT,
         k=3, hidden="G2", oracle=or_g2,
         notes="取材真实故障：日志区溢出把界面撑坏。屏幕尺寸要自己去 config 里找；"
               "陷阱是只留最早几行等于没解决"),
    Case(id="G1", dim="模糊新功能", suite="metrics_cli", prompt=G1_PROMPT,
         k=3, hidden="G1", oracle=or_g1,
         notes="陷阱：dev-a04 长期高温但没趋势，把「热」当「在变热」的实现会露馅"),
    Case(id="G5", dim="模糊新功能", suite="metrics_cli", prompt=G5_PROMPT,
         k=3, hidden="G5", oracle=or_g5,
         notes="不给字段名/格式，只要求「能带走看」；验收看文件真的生成且数值对得上"),
]
