#!/usr/bin/env python3
"""裸 LLM 评测的框架自检 —— 不调用任何模型。

两件事（借鉴 DeepSWE 的 `--agent oracle` 与「验证器出题时跑三次筛 flaky」）：

  1. oracle    ：用参考解跑每道编码题的 test，**必须全绿**。
                 挂了说明题目/断言自身有问题，此时模型分数不可信。
  2. self-check：同一份参考解重复判分 N 次，检测判分器抖动。
                 判分走子进程 + 15s 超时，机器忙时可能抖，抖动会被误记成模型答错。

用法：
  python3 selfcheck.py              # oracle + 3 次抖动检测
  python3 selfcheck.py --repeat 5
"""
from __future__ import annotations

import argparse
import sys

import full_eval as fe
from eval_lib import run_code_verdict
from oracles import ORACLES
from cases_hard import HARD, HARD_ORACLES


def all_code_cases():
    """返回 [(cid, lang, test)]，含 CODE、三语 TRI 与高密度 DENSE 卷。"""
    return ([(c[0], c[1], c[3]) for c in fe.CODE + fe.TRI]
            + [(c[0], c[1], c[3]) for c in HARD])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3, help="抖动检测重复次数")
    args = ap.parse_args()

    cases = all_code_cases()
    ORACLES.update(HARD_ORACLES)
    missing = [cid for cid, _, _ in cases if cid not in ORACLES]
    if missing:
        print(f"!! 以下用例缺参考解，无法自检: {missing}")

    print("=== ORACLE：参考解跑题目自带的 test，期望每条满分 ===\n")
    bad = []
    for cid, lang, test in cases:
        if cid not in ORACLES:
            continue
        v = run_code_verdict(ORACLES[cid], test)
        ok = v.passed and v.partial == 1.0
        print(f"  {'✓' if ok else '✗'} {cid:7}[{lang}] {v.summary()}  {v.detail[:70]}")
        if not ok:
            bad.append((cid, v))

    if bad:
        print(f"\n!! {len(bad)} 道题的参考解未满分 —— 题目/断言自身有问题，模型分数不可信：")
        for cid, v in bad:
            print(f"   {cid}: {v.summary()} {v.detail[:120]} {v.grader_error}")
        return 1
    print(f"\n全部 {len(cases)} 道题参考解满分，题目健康。\n")

    print(f"=== SELF-CHECK：每道题判分 {args.repeat} 次，检测 flaky ===\n")
    flaky = []
    for cid, lang, test in cases:
        if cid not in ORACLES:
            continue
        sigs = set()
        parts = []
        for _ in range(args.repeat):
            v = run_code_verdict(ORACLES[cid], test)
            sigs.add((v.passed, v.f2p_passed, v.f2p_total, v.p2p_passed, v.p2p_total))
            parts.append(round(v.partial, 3))
        stable = len(sigs) == 1
        print(f"  {'✓' if stable else '⚠'} {cid:7} partial={parts}")
        if not stable:
            flaky.append((cid, sigs))

    if flaky:
        print(f"\n!! {len(flaky)} 道题判分不稳定（应放宽超时或去掉时序依赖）：")
        for cid, sigs in flaky:
            print(f"   {cid}: {sigs}")
        return 1
    print(f"\n全部判分稳定。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
