#!/usr/bin/env python3
"""在工作目录里跑 pytest，返回逐条 node_id 的通过情况。

判分刻度就是「一条断言函数一分」：一个 node_id 展开成多少条测试就计多少分。
这是 F2P/P2P 比例的基础 —— 只看退出码的话，做对九成和什么都没做是同一个分数。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

_LINE = re.compile(r"^(\S+::\S+?)\s+(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\b")
_PASS_STATES = {"PASSED", "XFAIL"}


def find_python() -> str:
    """挑一个带 pytest 的解释器。

    历史坑：判分用的 pytest 只装在 pyenv 里，`/usr/bin/python3` 没有 —— 直接跑会「零条收集到」，
    而那看起来跟「模型把测试全弄坏了」一模一样。所以这里主动探测并在都没有时立刻报错。
    """
    cands = []
    if os.environ.get("EVAL_PY"):
        cands.append(os.environ["EVAL_PY"])
    cands += sorted(
        (str(p) for p in Path.home().glob(".pyenv/versions/3.1*/bin/python3")), reverse=True)
    cands += [sys.executable, shutil.which("python3") or "/usr/bin/python3"]
    for py in cands:
        if not py or not Path(py).exists():
            continue
        r = subprocess.run([py, "-c", "import pytest"], capture_output=True)
        if r.returncode == 0:
            return py
    raise RuntimeError("找不到带 pytest 的 Python 解释器；可用 EVAL_PY=... 指定")


PY = None       # 延迟探测，import 本模块时不去跑 subprocess


def python() -> str:
    global PY
    if PY is None:
        PY = find_python()
    return PY


@contextmanager
def injected(work: Path, files: dict):
    """把隐藏验收测试临时写进工作目录，退出时删除。

    模型运行阶段这些文件根本不在磁盘上，所以它只能照着自然语言需求实现，
    没法读断言反推（对应 DeepSWE「agent 与 verifier 分处两个容器」的设计）。
    """
    written = []
    try:
        for name, src in files.items():
            p = work / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src, encoding="utf-8")
            written.append(p)
        yield
    finally:
        for p in written:
            p.unlink(missing_ok=True)


def run(work: Path, targets=None, timeout: int = 300) -> tuple:
    """跑测试，返回 ({node_id: 是否通过}, 概要字符串)。

    targets 为 None 时跑工作目录下能收集到的全部测试。
    收集不到任何测试 → 返回空 dict，由调用方判定成 grader_error（框架/用例出问题），
    而不是记模型答错。
    """
    cmd = [python(), "-m", "pytest", "-v", "--tb=no", "-p", "no:cacheprovider",
           "-p", "no:randomly", "--continue-on-collection-errors", "-W", "ignore"]
    cmd += list(targets or [])
    try:
        p = subprocess.run(cmd, cwd=str(work), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {}, "PYTEST_TIMEOUT"
    out = {}
    for line in (p.stdout or "").splitlines():
        m = _LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2) in _PASS_STATES
    if not out:
        tail = " | ".join((p.stdout or p.stderr or "").strip().splitlines()[-3:])
        return {}, f"NO_TESTS: {tail[:200]}"
    n_ok = sum(1 for v in out.values() if v)
    return out, f"{n_ok}/{len(out)}"
