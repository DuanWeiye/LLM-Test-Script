#!/usr/bin/env python3
"""基线快照：在干净项目上跑一遍全部检查项，据此自动划分 F2P / P2P。

**为什么必须自动**：以前每个用例的 P2P 是人手写死的测试名列表，比如
「telemetry_kit 里基线本来就绿的是这 8 条」。这份名单极易写错：漏列一条，
模型明明没弄坏东西也永远拿不到满分；多列一条基线本来就红的，P2P 则永远不可能满分。
基线快照把这件事变成事实测量 —— 干净项目上跑一遍，红的就是要做到的（F2P），
绿的就是不许弄坏的（P2P）。

快照同时是**用例设计的体检**：
  - 可见测试基线必须全绿（不然模型一进来就看见红测试，等于被剧透了要改哪儿）
  - 隐藏验收测试基线必须至少红一条（全绿说明这题没提出任何新要求）
`run_eval.py --baseline` 会把不合格的用例直接点名。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import pytest_runner, vault, workspace

BASELINE_PATH = Path(__file__).resolve().parent.parent / "baseline.json"


def suite_fingerprint(suite: str) -> str:
    """模板目录内容指纹 —— 模板改了而基线没重算时给出警告。"""
    src = workspace.template_of(suite)
    h = hashlib.sha256()
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if workspace._is_noise(rel) or not p.is_file():
            continue
        h.update(str(rel).encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def hidden_files(case) -> dict:
    """取出该用例的隐藏验收测试 {文件名: 源码}。"""
    if not case.hidden:
        return {}
    return vault.unseal(case.hidden)


def measure(case) -> tuple:
    """在干净工作目录上测一次全部检查项，返回 ({node: ok}, 概要)。"""
    work = workspace.prepare(case.suite, drop=case.drop)
    try:
        files = hidden_files(case)
        with pytest_runner.injected(work, files):
            return pytest_runner.run(work, case.test_targets)
    finally:
        workspace.cleanup(work)


def compute(cases) -> dict:
    """算出全部用例的基线快照。"""
    snap = {}
    for case in cases:
        if not case.hidden and not case.test_targets:
            continue                       # 纯问答用例没有测试基线
        tests, detail = measure(case)
        snap[case.id] = {
            "suite": case.suite,
            "fingerprint": suite_fingerprint(case.suite),
            "detail": detail,
            "tests": tests,
        }
    return snap


def save(snap: dict):
    BASELINE_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


def load() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def audit(case, snap_entry: dict, hidden: dict) -> list:
    """检查一条用例的基线是否健康，返回问题列表（空＝健康）。"""
    problems = []
    tests = snap_entry.get("tests", {})
    if not tests:
        return [f"收集不到任何测试（{snap_entry.get('detail')}）"]

    hidden_names = set(hidden)
    def _is_hidden(node):
        return node.split("::")[0].split("/")[-1] in hidden_names

    visible_red = [n for n, ok in tests.items() if not ok and not _is_hidden(n)]
    hidden_nodes = [n for n in tests if _is_hidden(n)]
    hidden_red = [n for n in hidden_nodes if not tests[n]]

    if visible_red:
        problems.append(f"可见测试基线不绿（等于剧透改哪儿）：{visible_red[:3]}")
    if hidden and not hidden_nodes:
        problems.append("隐藏验收测试一条都没被收集到（文件名/路径不对？）")
    elif hidden_nodes and not hidden_red:
        problems.append("隐藏验收测试基线全绿 —— 这题没提出任何新要求，F2P 恒为空")
    if snap_entry.get("fingerprint") != suite_fingerprint(case.suite):
        problems.append("模板已改动但基线未重算（跑 --baseline）")
    return problems
