#!/usr/bin/env python3
"""Claude Code 外壳 · 本机 vs 云端模型对照评测 —— 运行引擎。

用法：
  python3 run_eval.py --models qwen3.6-35b-a3b,qwen3-coder-next --cases all --stamp phase1
  python3 run_eval.py --models claude-sonnet-4-6 --cases A1,A2 --k-default 1

每个用例在隔离的 git sandbox 里跑，跑前 reset 还原；用 stream-json 抓取工具调用与最终输出；
判分调用 eval_cases 里各用例的 grade 函数；汇总 pass@1 与 pass^k 写入 results/。
注意：必须用带 pytest 的解释器跑本脚本（PY 常量），且 claude CLI 在 PATH 中。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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


# ---------- 跑 claude 一次，解析 stream-json ----------
def run_claude(model, prompt, cwd, expose_md=False, timeout=600):
    settings = SETTINGS / f"{model}.json"
    claude_cmd = [
        "claude", "-p", prompt,
        "--settings", str(settings),
        "--setting-sources", "project",   # 关键：不加载 user ~/.claude/CLAUDE.md
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    # 用 bwrap 把 claude 关进只看得到 sandbox + settings 的命名空间：
    # 把 ~/Documents/md（标准答案文档）和整个 claude-eval（DESIGN/eval_cases 含答案/判分）tmpfs 遮空，
    # 再把 settings(只读) 与 sandbox(读写) 重新暴露 —— 防模型 grep/读到答案开卷（E1 泄题修复）。
    bwrap_cmd = [
        "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--bind", str(Path.home() / ".claude"), str(Path.home() / ".claude"),
        "--tmpfs", str(ROOT),                          # 总是遮蔽评测内部（DESIGN/eval_cases/判分逻辑）
        "--ro-bind", str(SETTINGS), str(SETTINGS),
        "--bind", str(SANDBOX), str(SANDBOX),
    ]
    if not expose_md and ANSWER_DOCS:
        bwrap_cmd += ["--tmpfs", ANSWER_DOCS]   # 闭卷：遮蔽答案文档目录（EVAL_ANSWER_DOCS）
    cmd = bwrap_cmd + ["--chdir", str(cwd)] + claude_cmd
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"result": "", "tools": [], "num_turns": None, "usage": {},
                "is_error": True, "wall": timeout, "stderr": "TIMEOUT", "raw_tail": ""}
    wall = time.time() - t0

    tools, result_text, num_turns, usage, is_error = [], "", None, {}, False
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "tool_use":
                    tools.append({"name": blk.get("name"), "input": blk.get("input", {})})
        elif t == "result":
            result_text = ev.get("result", "") or ""
            num_turns = ev.get("num_turns")
            usage = ev.get("usage", {})
            is_error = ev.get("is_error", False)
    return {"result": result_text, "tools": tools, "num_turns": num_turns,
            "usage": usage, "is_error": is_error, "wall": wall,
            "stderr": proc.stderr[-500:], "raw_tail": proc.stdout[-500:]}


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
    ap.add_argument("--models", required=True, help="逗号分隔 model（须有 settings/<m>.json）")
    ap.add_argument("--cases", default="all", help="逗号分隔用例 id，或 all")
    ap.add_argument("--k-default", type=int, default=None, help="覆盖每个用例的默认 k")
    ap.add_argument("--stamp", default="run", help="结果文件标签")
    args = ap.parse_args()

    import eval_cases
    all_cases = eval_cases.CASES
    if args.cases == "all":
        sel = list(all_cases)
    else:
        want = args.cases.split(",")
        sel = [c for c in all_cases if c.id in want]

    models = args.models.split(",")
    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / f"results_{args.stamp}.json"
    out = {}

    for model in models:
        if not (SETTINGS / f"{model}.json").exists():
            print(f"!! 跳过 {model}：缺 settings/{model}.json", flush=True)
            continue
        out[model] = {}
        print(f"\n########## {model} ##########", flush=True)
        for case in sel:
            k = args.k_default or case.k
            runs = []
            for i in range(k):
                reset_sandbox()
                cwd = SANDBOX / case.cwd
                ctx = run_claude(model, case.prompt, cwd, expose_md=case.expose_md)
                ctx.update(sandbox=SANDBOX, cwd=cwd, run_pytest=run_pytest, PY=PY)
                try:
                    passed, detail = case.grade(ctx)
                except Exception as e:
                    passed, detail = False, f"grade异常:{str(e)[:140]}"
                rec = {"passed": bool(passed), "detail": detail,
                       "tools": [t["name"] for t in ctx["tools"]],
                       "n_tools": len(ctx["tools"]),
                       "wall": round(ctx["wall"], 1),
                       "result_head": ctx["result"][:800]}
                # E 类（rubric 主观判分）存全文，便于离线复核/重判，避免改判分后必须重跑
                if case.dim.startswith("复杂诊断") or case.id.startswith("E"):
                    rec["result_full"] = ctx["result"]
                runs.append(rec)
                print(f"  {case.id} [{i+1}/{k}] {'✓' if passed else '✗'} "
                      f"(tools={len(ctx['tools'])}) {detail[:80]}", flush=True)
            n_pass = sum(1 for r in runs if r["passed"])
            out[model][case.id] = {"dim": case.dim, "k": k,
                                   "pass_at_1": round(n_pass / k, 3),
                                   "pass_k": 1.0 if n_pass == k else 0.0,
                                   "n_pass": n_pass, "runs": runs}
            json.dump(out, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"\n=== 完成，结果写入 {out_path} ===", flush=True)


if __name__ == "__main__":
    main()
