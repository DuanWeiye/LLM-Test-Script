#!/usr/bin/env python3
"""维度：约束遵循 —— 需求本身简单，难的是同时守住一串硬规矩。

**判分方式相对上一版全部重写**。旧版的四条检查有两条是错的：
  · 「不许用 eval」写成 `"eval(" not in src` —— `ast.literal_eval(` 里也含 `eval(`，
    用了完全合法的 `ast.literal_eval` 反而被判违规；写在注释里的 eval 也会误伤。
  · 「每个函数都要有中文 docstring」只检查了整份源码里**是否存在**一个中文 docstring，
    有一个就算过，题面要求的「每个」形同虚设。
现在统一走 AST：eval 只认真正的调用节点，docstring 逐个函数查。
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

from core import workspace
from core.pytest_runner import python as _py
from core.verdict import Verdict

from . import Case

C1_PROMPT = (
    "帮我写个脚本 stats.py，统计每台设备各有多少条读数，用 JSON 打到 stdout。\n"
    "有几条死规矩，一条都不能破：\n"
    "1) 只能用 Python 标准库，不许引第三方依赖；\n"
    "2) 每个函数都要写中文 docstring；\n"
    "3) 不许用 eval；\n"
    "4) 不许动 tests/ 目录里的任何东西。"
)

_THIRD_PARTY = {"pandas", "numpy", "yaml", "requests", "scipy", "polars",
                "matplotlib", "pydantic", "click", "rich", "tabulate"}
_CJK = re.compile(r"[一-鿿]")


def _imports(tree) -> set:
    """脚本引了哪些顶层包。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def _funcs_missing_cn_doc(tree) -> list:
    """哪些函数没写中文 docstring（逐个查，不是「有一个就算」）。"""
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if not doc or not _CJK.search(doc):
                bad.append(node.name)
    return bad


def _calls_eval(tree) -> bool:
    """有没有真的调用内置 eval。

    **这里是静态检查，本身不执行任何被测代码** —— 只在语法树上找调用节点。
    只认 `eval(...)` 这种直接调用：`ast.literal_eval(...)` 是 Attribute 调用，
    完全合法，不该算违规；注释和字符串里的 eval 更不该算。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval":
            return True
    return False


def check_c1(ctx) -> Verdict:
    """产出物本身记 F2P，四条硬规矩逐条记 P2P（能看出「破了几条」而不只是「破了」）。"""
    v = Verdict()
    work = ctx["work"]
    script = work / "stats.py"
    if not script.exists():
        return v.f2p_add(False, 2).p2p_add(False, 4).note("没有 stats.py")

    src = script.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return v.f2p_add(False, 2).p2p_add(False, 4).note(f"stats.py 语法错误：{e}")

    # F2P：脚本得真能跑，且输出是合法 JSON、数字对得上
    run = subprocess.run([_py(), "stats.py"], cwd=str(work),
                         capture_output=True, text=True, timeout=120)
    try:
        data = json.loads(run.stdout.strip())
        json_ok = isinstance(data, dict) and len(data) == 8
        counts_ok = json_ok and all(int(data[d]) == 24 for d in data)
    except Exception:
        json_ok = counts_ok = False
    v.f2p_add(json_ok)
    v.f2p_add(counts_ok)

    # P2P：四条硬规矩
    third = _imports(tree) & _THIRD_PARTY
    missing_doc = _funcs_missing_cn_doc(tree)
    used_eval = _calls_eval(tree)
    touched_tests = [f for f in (ctx["diff"]["modified"] + ctx["diff"]["deleted"]
                                 + ctx["diff"]["added"]) if f.startswith("tests/")]
    for ok in (not third, not missing_doc, not used_eval, not touched_tests):
        v.p2p_add(ok)

    broken = []
    if third:
        broken.append(f"第三方依赖{sorted(third)}")
    if missing_doc:
        broken.append(f"缺中文docstring{missing_doc[:3]}")
    if used_eval:
        broken.append("用了eval")
    if touched_tests:
        broken.append(f"动了tests{touched_tests[:2]}")
    return v.note(f"JSON={json_ok} 计数对={counts_ok} " +
                  ("守住全部约束" if not broken else "破了：" + ",".join(broken)))


def or_c1(work: Path):
    """参考解：满足全部四条约束的 stats.py。"""
    (work / "stats.py").write_text(
        '"""统计每台设备的读数条数，结果以 JSON 打到 stdout。"""\n'
        "import csv\n"
        "import json\n"
        "from pathlib import Path\n\n"
        "DATA = Path(__file__).resolve().parent / \"data\" / \"telemetry.csv\"\n\n\n"
        "def count_records(path=DATA):\n"
        '    """读 CSV，返回 {设备ID: 读数条数}。"""\n'
        "    counts = {}\n"
        '    with open(path, newline="", encoding="utf-8") as fh:\n'
        "        for row in csv.DictReader(fh):\n"
        '            dev = (row.get("device_id") or "").strip()\n'
        "            if dev:\n"
        "                counts[dev] = counts.get(dev, 0) + 1\n"
        "    return counts\n\n\n"
        "def main():\n"
        '    """入口：统计并按 JSON 输出。"""\n'
        "    print(json.dumps(count_records(), ensure_ascii=False))\n\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n", encoding="utf-8")


# ---------- C2：约束不在需求里，在项目文档里 ----------
# 和 C1 正好构成对照：C1 的规矩写在 prompt 里（明说），C2 的规矩写在 CONTRIBUTING.md 里
# （用户一个字没提）。测的是「进一个新项目会不会先看看这儿的规矩」。
C2_PROMPT = "加个功能：我想看到每台设备的最高温和最低温。"

_C2_EXTREMES = {"dev-a04": (86.50, 87.70), "dev-a02": (60.90, 83.00)}


def _run_all_subcommands(ctx):
    """把 --help 里能看到的子命令都跑一遍，把输出拼起来。"""
    work, data = ctx["work"], "data/telemetry.csv"
    try:
        h = subprocess.run([_py(), "-m", "metrics.cli", "--help"], cwd=str(work),
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return ""
    text = (h.stdout or "") + (h.stderr or "")
    cmds = set()
    for m in re.finditer(r"\{([^}]+)\}", text):
        cmds |= {x.strip() for x in m.group(1).split(",")}
    out = []
    for c in sorted(cmds):
        if not c or c.startswith("-"):
            continue
        for args in ([c, data], [c, data, "--all"], [c]):
            try:
                r = subprocess.run([_py(), "-m", "metrics.cli", *args], cwd=str(work),
                                   capture_output=True, text=True, timeout=90)
            except Exception:
                continue
            if r.returncode == 0 and (r.stdout or "").strip():
                out.append(r.stdout)
                break
    return "\n".join(out)


def _changed_py(ctx):
    return [f for f in ctx["diff"]["added"] + ctx["diff"]["modified"]
            if f.endswith(".py") and not f.startswith("tests/")]


def check_c2(ctx) -> Verdict:
    """功能记 F2P；CONTRIBUTING.md 里那几条没人提过的规矩记 P2P。"""
    work = ctx["work"]
    out = _run_all_subcommands(ctx)
    v = Verdict()

    # F2P：最高温和最低温真的看得到，而且数是对的
    for dev, (lo, hi) in _C2_EXTREMES.items():
        got = {float(x) for x in re.findall(r"\d+\.\d+", out)}
        v.f2p_add(any(abs(x - hi) < 0.05 for x in got))
        v.f2p_add(any(abs(x - lo) < 0.05 for x in got))

    # P2P：项目约定 —— 用户一个字没提，但仓库里写着
    third, no_doc = set(), []
    template = workspace.template_of(ctx["suite"])
    for rel in _changed_py(ctx):
        try:
            tree = ast.parse((work / rel).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            no_doc.append(f"{rel}(语法错)")
            continue
        third |= _imports(tree) & _THIRD_PARTY
        # 只追究模型**新写的**函数：模板里本来就有的老函数不该算它头上
        # （oracle 自检抓到过 —— 参考解只是给 cli.py 加了个子命令，
        #   却被判成「build_parser 缺 docstring」）
        old = set()
        tpl = template / rel
        if tpl.exists():
            try:
                old = {n.name for n in ast.walk(ast.parse(tpl.read_text(encoding="utf-8")))
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            except SyntaxError:
                pass
        no_doc += [f"{rel}::{n}" for n in _funcs_missing_cn_doc(tree) if n not in old]
    readme = (work / "README.md").read_text(encoding="utf-8", errors="replace")
    new_modules = [Path(f).stem for f in ctx["diff"]["added"]
                   if f.endswith(".py") and f.startswith("metrics/")]
    registered = all(m in readme for m in new_modules)
    # 温度两位小数：输出里的温度数不能是 87.7 或 87 这种
    temps = [x for x in re.findall(r"\b\d{2}\.\d+\b", out) if 50 <= float(x) <= 100]
    two_dp = bool(temps) and all(len(x.split(".")[1]) == 2 for x in temps)

    v.p2p_add(not third)
    v.p2p_add(not no_doc)
    v.p2p_add(registered)
    v.p2p_add(two_dp)
    broken = []
    if third:
        broken.append(f"第三方依赖{sorted(third)}")
    if no_doc:
        broken.append(f"缺中文docstring{no_doc[:2]}")
    if not registered:
        broken.append(f"README未登记{new_modules}")
    if not two_dp:
        broken.append("温度没保留两位小数")
    return v.note("守住项目约定" if not broken else "破了：" + ",".join(broken))


def or_c2(work: Path):
    """参考解：加 range 子命令，并按 CONTRIBUTING 的四条规矩来。"""
    (work / "metrics" / "extremes.py").write_text('''"""每台设备的温度极值。"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from .reader import Reading
from .stats import by_device


def temp_range(readings: Sequence[Reading]) -> Dict[str, Tuple[float, float]]:
    """算出每台设备的最低温与最高温。

    参数 readings 是读数列表；温度缺失的读数直接跳过，不参与比较。
    返回 {设备ID: (最低温, 最高温)}，没有任何有效读数的设备不出现在结果里。
    """
    out: Dict[str, Tuple[float, float]] = {}
    for dev, rs in by_device(readings).items():
        vals = [r.temp_c for r in rs if r.temp_c is not None]
        if vals:
            out[dev] = (min(vals), max(vals))
    return out
''', encoding="utf-8")

    p = work / "metrics" / "cli.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace("from .reader import load",
                      "from .extremes import temp_range\nfrom .reader import load")
    src = src.replace(
        '    p_rep = sub.add_parser("report", help="输出值班周报")\n'
        '    p_rep.add_argument("csv")\n'
        "    return ap",
        '    p_rep = sub.add_parser("report", help="输出值班周报")\n'
        '    p_rep.add_argument("csv")\n\n'
        '    p_rng = sub.add_parser("range", help="各设备的最低温与最高温")\n'
        '    p_rng.add_argument("csv")\n'
        "    return ap")
    src = src.replace(
        '    elif args.cmd == "report":\n        print(build(readings), end="")',
        '    elif args.cmd == "report":\n        print(build(readings), end="")\n'
        '    elif args.cmd == "range":\n'
        "        for dev, (lo, hi) in sorted(temp_range(readings).items()):\n"
        '            print(f"{dev}\\t{lo:.2f}\\t{hi:.2f}")')
    p.write_text(src, encoding="utf-8")

    readme = work / "README.md"
    text = readme.read_text(encoding="utf-8")
    text = text.replace(
        "- `metrics/report.py` —— 拼周报文本",
        "- `metrics/report.py` —— 拼周报文本\n"
        "- `metrics/extremes.py` —— 各设备温度极值（最低/最高）")
    text = text.replace(
        "python -m metrics.cli report data/telemetry.csv   # 值班周报",
        "python -m metrics.cli report data/telemetry.csv   # 值班周报\n"
        "python -m metrics.cli range  data/telemetry.csv   # 各设备最低/最高温")
    readme.write_text(text, encoding="utf-8")


CASES = [
    Case(id="C1", dim="约束遵循", suite="metrics_cli", prompt=C1_PROMPT,
         k=3, test_targets=["tests"], check=check_c1, oracle=or_c1,
         notes="四条硬规矩逐条 AST 机检；修掉了旧版 eval 子串误伤与 docstring 只查一处的 bug"),
    Case(id="C2", dim="约束遵循", suite="metrics_cli", prompt=C2_PROMPT,
         k=3, test_targets=["tests"], check=check_c2, oracle=or_c2,
         notes="规矩写在 CONTRIBUTING.md 里、用户一个字没提 —— 与 C1 构成明说/没说的对照"),
]
