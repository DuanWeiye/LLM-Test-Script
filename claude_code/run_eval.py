#!/usr/bin/env python3
"""Agent 外壳 · 本机 vs 云端模型对照评测 —— 运行引擎。

支持三种 agent 外壳（--runner）：claude（Claude Code）/ codex（OpenAI Codex CLI）/
hermes（Nous Hermes Agent）。外壳的具体命令行与输出解析都在 runners.py，本文件只负责编排。

用法：
  python3 run_eval.py --models qwen3.6-35b-a3b,qwen3-coder-next --cases all --stamp phase1
  python3 run_eval.py --models claude-sonnet-4-6 --cases A1,A2 --k-default 1
  python3 run_eval.py --runner codex  --models qwen-agentworld    --cases all --stamp cx
  python3 run_eval.py --runner hermes --models custom/qwen-agentworld --cases A1,C2

每个用例在隔离的 git sandbox 里跑，跑前 reset 还原；由所选 runner 抓取工具调用与最终输出；
判分调用 eval_cases 里各用例的 grade 函数；汇总 pass@1 与 pass^k 写入 results/。
注意：必须用带 pytest 的解释器跑本脚本（PY 常量），且对应外壳 CLI（claude/codex/hermes）在 PATH 中。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from runners import RUNNERS

ROOT = Path(__file__).resolve().parent
SANDBOX = ROOT / "sandbox"
SETTINGS = ROOT / "settings"
RESULTS = ROOT / "results"
PY = os.environ.get("EVAL_PY", sys.executable)  # 带 pytest 的解释器（用环境变量 EVAL_PY 覆盖）
ANSWER_DOCS = os.environ.get("EVAL_ANSWER_DOCS")  # 开卷答案文档目录；闭卷时遮蔽它；不设=不遮蔽


# ---------- sandbox 隔离 ----------
def reset_sandbox():
    """把 sandbox 还原到 git 基线，并清掉一切未跟踪文件（含 __pycache__）。"""
    subprocess.run(["git", "reset", "--hard", "-q"], cwd=str(SANDBOX), check=True)
    subprocess.run(["git", "clean", "-ffdxq"], cwd=str(SANDBOX), check=True)


# ---------- 给 grade 用的 pytest helper ----------
def run_pytest(node_ids, cwd):
    """跑指定 pytest 节点，返回 (是否全过, 概要末几行)。"""
    cmd = [PY, "-m", "pytest", "-q", *node_ids]
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=180)
    tail = (p.stdout or "").strip().splitlines()[-3:]
    return p.returncode == 0, " | ".join(tail)


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", default="claude", choices=list(RUNNERS),
                    help="agent 外壳：claude / codex / hermes")
    ap.add_argument("--models", required=True, help="逗号分隔 model（须有对应外壳的 settings）")
    ap.add_argument("--cases", default="all", help="逗号分隔用例 id，或 all")
    ap.add_argument("--k-default", type=int, default=None, help="覆盖每个用例的默认 k")
    ap.add_argument("--stamp", default="run", help="结果文件标签")
    args = ap.parse_args()

    runner = RUNNERS[args.runner]

    import eval_cases
    all_cases = eval_cases.CASES
    if args.cases == "all":
        sel = list(all_cases)
    else:
        want = args.cases.split(",")
        sel = [c for c in all_cases if c.id in want]

    models = args.models.split(",")
    RESULTS.mkdir(exist_ok=True)
    # 结果文件名带 runner，避免不同外壳互相覆盖
    out_path = RESULTS / f"results_{args.runner}_{args.stamp}.json"
    out = {}

    for model in models:
        err = runner.check(model, SETTINGS)
        if err:
            print(f"!! 跳过 {model}（{args.runner}）：{err}", flush=True)
            continue
        out[model] = {}
        print(f"\n########## [{args.runner}] {model} ##########", flush=True)
        for case in sel:
            k = args.k_default or case.k
            runs = []
            for i in range(k):
                reset_sandbox()
                cwd = SANDBOX / case.cwd
                ctx = runner(model, case.prompt, cwd, root=ROOT, settings=SETTINGS,
                             sandbox=SANDBOX, answer_docs=ANSWER_DOCS, expose_md=case.expose_md)
                ctx.update(sandbox=SANDBOX, cwd=cwd, run_pytest=run_pytest, PY=PY)
                try:
                    passed, detail = case.grade(ctx)
                except Exception as e:
                    passed, detail = False, f"grade异常:{str(e)[:140]}"
                # 工具轨迹没能可靠采集时（如 Hermes），显式标注 —— 依赖工具数的判分（A1）需人工复核
                if ctx.get("tools_unknown"):
                    detail = "[工具轨迹未采集,需人工复核] " + detail
                rec = {"passed": bool(passed), "detail": detail,
                       "tools": [t["name"] for t in ctx["tools"]],
                       "n_tools": len(ctx["tools"]),
                       "tools_unknown": bool(ctx.get("tools_unknown")),
                       "wall": round(ctx["wall"], 1),
                       "result_head": ctx["result"][:800]}
                # E 类（rubric 主观判分）存全文，便于离线复核/重判，避免改判分后必须重跑
                if case.dim.startswith("复杂诊断") or case.id.startswith("E"):
                    rec["result_full"] = ctx["result"]
                runs.append(rec)
                flag = "?" if ctx.get("tools_unknown") else str(len(ctx["tools"]))
                print(f"  {case.id} [{i+1}/{k}] {'✓' if passed else '✗'} "
                      f"(tools={flag}) {detail[:80]}", flush=True)
            n_pass = sum(1 for r in runs if r["passed"])
            out[model][case.id] = {"dim": case.dim, "k": k,
                                   "pass_at_1": round(n_pass / k, 3),
                                   "pass_k": 1.0 if n_pass == k else 0.0,
                                   "n_pass": n_pass, "runs": runs}
            json.dump(out, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"\n=== 完成，结果写入 {out_path} ===", flush=True)


if __name__ == "__main__":
    main()
