#!/usr/bin/env python3
"""Claude Code 外壳 · 多模型对照评测 —— 运行引擎。

同一个 Claude Code 外壳，只换底层模型 endpoint，比的是 **agent 场景下的真实差距**。

    # 三道自检（不调用任何 LLM，改判分/改用例后都要跑）
    python3 run_eval.py --baseline              # 量基线：验用例设计健康 + 自动划分 F2P/P2P
    python3 run_eval.py --oracle                # 跑参考解：每条必须满分
    python3 run_eval.py --self-check --repeat 3 # 重复判分：测判分器抖不抖

    # 正式评测
    python3 run_eval.py --models qwen3.6-35b-a3b --cases all --stamp run1

    # 开放题（诊断类）离线判分：评测阶段只存全文，判分单独跑，避免裁判模型
    # 和被测模型来回热切换
    python3 run_eval.py --judge results/results_run1.json
    python3 run_eval.py --judge-check           # 裁判自己先过自检

**不需要任何 sudo / sysctl**：隔离靠「/tmp 中性工作目录 + 验收测试存保管库 +
--setting-sources project」三层，见 core/workspace.py 与 core/vault.py。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases as case_lib                                    # noqa: E402
from core import baseline, judge, runner, workspace         # noqa: E402
from core.verdict import Verdict                            # noqa: E402

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def select(spec: str) -> list:
    if spec == "all":
        return list(case_lib.CASES)
    want = [s.strip() for s in spec.split(",") if s.strip()]
    sel = case_lib.by_id(want)
    missing = set(want) - {c.id for c in sel}
    if missing:
        raise SystemExit(f"没有这些用例：{sorted(missing)}")
    return sel


# ---------- 自检一：基线快照 ----------
def cmd_baseline(cases) -> int:
    print("=== 量基线：干净项目上跑一遍全部检查项 ===\n")
    # 增量合并：`--baseline --cases X` 只想重量 X，不该把别的用例的基线冲掉
    # （第一版就是直接覆盖，一按用例量基线，其余用例立刻全部「没有基线快照」）
    snap = baseline.load()
    snap.update(baseline.compute(cases))
    known = {c.id for c in case_lib.CASES}
    snap = {k: v for k, v in snap.items() if k in known}      # 顺手清掉已删用例的残留
    baseline.save(snap)
    bad = []
    for case in cases:
        entry = snap.get(case.id)
        if entry is None:
            print(f"  ·  {case.id:5} {case.dim:14} 纯问答/开放题，无测试基线")
            continue
        problems = baseline.audit(case, entry, baseline.hidden_files(case))
        tests = entry["tests"]
        n_red = sum(1 for ok in tests.values() if not ok)
        print(f"  {'✓' if not problems else '✗'} {case.id:5} {case.dim:14} "
              f"共{len(tests):3}项 → F2P {n_red:2} / P2P {len(tests) - n_red:2}")
        for p in problems:
            print(f"        ! {p}")
        if problems:
            bad.append(case.id)
    print()
    if bad:
        print(f"!! {len(bad)} 条用例基线不健康：{bad}")
        return 1
    print(f"基线已写入 {baseline.BASELINE_PATH}")
    return 0


# ---------- 自检二/三：参考解 ----------
def run_oracle_once(case) -> Verdict:
    """还原干净项目 → 应用参考解 → 判分。参考解必须满分。"""
    if case.oracle is None:
        return Verdict().fail_grader("该用例没有参考解(oracle)")
    work = workspace.prepare(case.suite, drop=case.drop)
    try:
        override = case.oracle(work) or {}
        base = {"result": "", "tools": [], "num_turns": 1, "usage": {},
                "aborted": "", "wall": 0.0, "stderr": "", "raw_tail": ""}
        base.update(override)
        ctx = case_lib.make_ctx(case, work, base)
        return case_lib.grade(case, ctx)
    finally:
        workspace.cleanup(work)


def cmd_oracle(cases) -> int:
    """验证「用例 + 判分逻辑 + 项目模板」三者本身是好的。

    这是判断「分数低是模型菜、还是评测自己坏了」的唯一可靠手段。
    任何一条参考解没满分，同批模型分数就都不可信。
    """
    print("=== ORACLE 自检：跑参考解，期望每条满分 ===\n")
    bad = []
    for case in cases:
        if case.is_open_ended:
            print(f"  ·  {case.id:5} 开放题，参考解交给 --judge-check")
            continue
        v = run_oracle_once(case)
        ok = v.passed and v.partial == 1.0
        print(f"  {'✓' if ok else '✗'} {case.id:5} {case.dim:14} {v.summary()}  {v.detail[:70]}")
        if not ok:
            bad.append((case.id, v))
    print()
    if bad:
        print(f"!! {len(bad)} 条参考解未满分 —— 评测框架自身有问题，模型分数不可信：")
        for cid, v in bad:
            print(f"   {cid}: {v.summary()} {v.detail[:120]} {v.grader_error}")
        return 1
    print("全部参考解满分，框架健康。")
    return 0


def cmd_self_check(cases, repeat) -> int:
    """同一份参考解重复判分，检测判分器抖动。

    判分里有 subprocess、pytest、超时和文件读写，机器忙时可能抖 ——
    抖动会被误记成「模型这次没做到」，是最难发现的一类假信号。
    """
    print(f"=== SELF-CHECK：每条参考解判分 {repeat} 次，测 flaky ===\n")
    flaky = []
    for case in cases:
        if case.is_open_ended or case.oracle is None:
            continue
        sigs, parts = set(), []
        for _ in range(repeat):
            v = run_oracle_once(case)
            sigs.add((v.passed, v.f2p_passed, v.f2p_total, v.p2p_passed, v.p2p_total))
            parts.append(round(v.partial, 3))
        stable = len(sigs) == 1
        print(f"  {'✓' if stable else '⚠'} {case.id:5} partial={parts}")
        if not stable:
            flaky.append((case.id, sigs))
    print()
    if flaky:
        print(f"!! {len(flaky)} 条判分不稳定，应修判分逻辑（放宽超时 / 去掉时序依赖）：")
        for cid, sigs in flaky:
            print(f"   {cid}: {sigs}")
        return 1
    print("全部判分稳定。")
    return 0


# ---------- 开放题：离线裁判 ----------
def cmd_judge_check(cases) -> int:
    """裁判自己先过自检：拿标注好的样本考它，判错太多就不许用它的结论。"""
    from cases import diagnosis
    print(f"=== 裁判自检：{judge.JUDGE_MODEL} @ {judge.JUDGE_BASE} ===\n")
    rows, acc = judge.check(diagnosis.JUDGE_FIXTURES, diagnosis.RUBRIC)
    for r in rows:
        if r.get("error"):
            print(f"  !! {r['name']}: {r['error']}")
        else:
            print(f"  {'✓' if not r['wrong'] else '✗'} {r['name']:24} 判错 {r['n_wrong']} 项"
                  + (f" → {r['wrong'][:3]}" if r["wrong"] else ""))
    print(f"\n裁判逐项正确率 {acc:.1%}")
    if acc < 0.9:
        print("!! 裁判不够可靠（<90%），换裁判模型或改判据描述，别拿它的结论写结论。")
        return 1
    return 0


def cmd_judge(path: Path) -> int:
    """离线给结果文件里的开放题判分，判完写回同一个文件。"""
    from cases import diagnosis
    data = json.loads(path.read_text(encoding="utf-8"))
    open_ids = {c.id for c in case_lib.CASES if c.is_open_ended}
    n = 0
    for model, cs in data.items():
        for cid, rec in cs.items():
            if cid not in open_ids:
                continue
            case = case_lib.by_id([cid])[0]
            for i, run in enumerate(rec.get("runs", [])):
                text = run.get("result_full") or run.get("result_head") or ""
                if not text.strip():
                    continue
                try:
                    judged = judge.call(text, case.rubric)
                except Exception as ex:
                    print(f"  !! 裁判失败 {model}/{cid}[{i}]: {str(ex)[:120]}")
                    continue
                v = judge.to_verdict(judged, case.rubric)
                run.update(v.as_dict())
                run["judge"] = judged
                run["kw_screen"] = diagnosis.keyword_screen(text, case.rubric)
                n += 1
                print(f"  {model:22} {cid:5}[{i}] {v.summary()}")
            runs = rec.get("runs", [])
            if runs:
                k = len(runs)
                n_pass = sum(1 for r in runs if r.get("passed"))
                rec.update(pass_at_1=round(n_pass / k, 3),
                           pass_pow_k=1.0 if n_pass == k else 0.0, n_pass=n_pass,
                           partial_mean=round(sum(r.get("partial", 0) for r in runs) / k, 4),
                           f2p_mean=round(sum(r.get("f2p", 0) for r in runs) / k, 4),
                           p2p_mean=round(sum(r.get("p2p", 0) for r in runs) / k, 4))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== 判了 {n} 份，写回 {path} ===")
    return 0


# ---------- 结果汇总 ----------
def _cell(rec) -> str:
    """一个格子：pass@1（partial 均值）。全或无与细粒度都要看得到。"""
    p1, part = rec.get("pass_at_1", 0.0), rec.get("partial_mean", 0.0)
    mark = ""
    runs = rec.get("runs", [])
    if any(r.get("aborted") for r in runs):
        mark = "⚠"
    if any(r.get("grader_error") for r in runs):
        mark = "❗"
    return f"{p1:.2f} ({part:.2f}){mark}"


def cmd_report(paths) -> int:
    """把一个或多个结果文件汇总成 markdown 报告。

    格子里是 `pass@1 (partial)`：前者是全或无口径，后者在饱和区仍能区分模型。
    ⚠＝有运行被中断（超时/空输出），❗＝判分器自己出错 —— 两者都不是「模型答错」，要单独看。
    """
    data = {}
    for p in paths:
        for model, cs in json.loads(Path(p).read_text(encoding="utf-8")).items():
            data.setdefault(model, {}).update(cs)
    if not data:
        print("没有可汇总的结果")
        return 1

    models = list(data)
    order = [c for c in case_lib.CASES if any(c.id in data[m] for m in models)]
    lines = ["# 评测结果汇总", "",
             f"> 被测模型：{', '.join(models)}",
             "> 格子＝`pass@1 (partial 均值)`；⚠ 有运行被中断，❗ 判分器出错（都不算模型答错）。", ""]

    lines += ["## 逐用例", "",
              "| 用例 | 维度 | k | " + " | ".join(models) + " |",
              "|---|---|---|" + "---|" * len(models)]
    for case in order:
        row = [case.id, case.dim, str(case.k)]
        for m in models:
            row.append(_cell(data[m][case.id]) if case.id in data[m] else "—")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## 按维度", "",
              "| 维度 | " + " | ".join(models) + " |",
              "|---|" + "---|" * len(models)]
    dims = []
    for c in order:
        if c.dim not in dims:
            dims.append(c.dim)
    for dim in dims:
        row = [dim]
        for m in models:
            recs = [data[m][c.id] for c in order if c.dim == dim and c.id in data[m]]
            if not recs:
                row.append("—")
                continue
            p1 = sum(r.get("pass_at_1", 0) for r in recs) / len(recs)
            part = sum(r.get("partial_mean", 0) for r in recs) / len(recs)
            row.append(f"{p1:.2f} ({part:.2f})")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## 行为观察", "",
              "| 模型 | 总运行 | 平均工具数 | 平均耗时 | 中断 | 判分器故障 |",
              "|---|---|---|---|---|---|"]
    for m in models:
        runs = [r for cs in data[m].values() for r in cs.get("runs", [])]
        if not runs:
            continue
        n_abort = sum(1 for r in runs if r.get("aborted"))
        n_gerr = sum(1 for r in runs if r.get("grader_error"))
        lines.append(f"| {m} | {len(runs)} | "
                     f"{sum(r.get('n_tools', 0) for r in runs) / len(runs):.1f} | "
                     f"{sum(r.get('wall', 0) for r in runs) / len(runs):.0f}s | "
                     f"{n_abort} | {n_gerr} |")

    # 开放题：把裁判逐点命中摊开，顺便标出与关键词快筛的分歧
    open_ids = [c.id for c in order if c.is_open_ended]
    if open_ids:
        lines += ["", "## 开放题（裁判逐点）", ""]
        for cid in open_ids:
            lines.append(f"### {cid}")
            for m in models:
                for i, r in enumerate(data[m].get(cid, {}).get("runs", [])):
                    j = r.get("judge")
                    if not j:
                        lines.append(f"- {m} [{i}] 尚未判分（跑 `--judge`）")
                        continue
                    hit = [k for k, v in j.get("points", {}).items() if v]
                    bad = [k for k, v in j.get("negatives", {}).items() if v]
                    kw = r.get("kw_screen", {})
                    diff = [k for k in j.get("points", {})
                            if bool(kw.get(k)) != bool(j["points"][k])] if kw else []
                    lines.append(
                        f"- {m} [{i}] 命中 {len(hit)}/{len(j.get('points', {}))}"
                        + (f"；错误结论：{','.join(bad)}" if bad else "")
                        + (f"；与关键词快筛分歧：{','.join(diff)}" if diff else "")
                        + f"\n  - 命中项：{'、'.join(hit) or '无'}")
            lines.append("")

    stamp = Path(paths[0]).stem.replace("results_", "")
    out = RESULTS / f"REPORT_{stamp}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\n=== 报告写入 {out} ===")
    return 0


# ---------- 正式评测 ----------
def cmd_run(models, cases, stamp, k_override, effort=None) -> int:
    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / f"results_{stamp}.json"
    out = {}
    swept = workspace.sweep_stale()
    if swept:
        print(f"（清理了 {swept} 个历史遗留的运行目录）")

    for model in models:
        if not runner.settings_path(model).exists():
            print(f"!! 跳过 {model}：缺 settings/{model}.json", flush=True)
            continue
        out[model] = {}
        print(f"\n########## {model} ##########", flush=True)
        for case in cases:
            k = k_override or case.k
            runs = []
            for i in range(k):
                work = workspace.prepare(case.suite, drop=case.drop)
                try:
                    run_out = runner.run_claude(model, case.prompt, work,
                                                timeout=case.timeout, effort=effort)
                    ctx = case_lib.make_ctx(case, work, run_out)
                    v = case_lib.grade(case, ctx)
                    rec = {**v.as_dict(),
                           "tools": runner.tool_names(ctx),
                           "n_tools": len(ctx["tools"]),
                           "wall": round(ctx["wall"], 1),
                           "changed": ctx["diff"],
                           "result_head": ctx["result"][:800]}
                    if effort:
                        # 记在 run 级而不是文件级：加文件级元信息键会被 --judge / --report
                        # 的「遍历每个键都当用例」逻辑吃掉
                        rec["effort"] = effort
                    if case.is_open_ended:
                        rec["result_full"] = ctx["result"]   # 供离线裁判判分/重判
                finally:
                    workspace.cleanup(work)
                runs.append(rec)
                mark = "?" if case.is_open_ended else ("✓" if v.passed else "✗")
                print(f"  {case.id} [{i+1}/{k}] {mark} (tools={rec['n_tools']}) "
                      f"{v.summary()} {v.detail[:60]}", flush=True)
            n_pass = sum(1 for r in runs if r["passed"])
            out[model][case.id] = {
                "dim": case.dim, "k": k, "open_ended": case.is_open_ended,
                "pass_at_1": round(n_pass / k, 3),
                "pass_pow_k": 1.0 if n_pass == k else 0.0,
                "n_pass": n_pass,
                "partial_mean": round(sum(r["partial"] for r in runs) / k, 4),
                "f2p_mean": round(sum(r["f2p"] for r in runs) / k, 4),
                "p2p_mean": round(sum(r["p2p"] for r in runs) / k, 4),
                "runs": runs}
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== 完成，结果写入 {out_path} ===", flush=True)
    if any(c.is_open_ended for c in cases):
        print(f"开放题还需离线判分：python3 run_eval.py --judge {out_path}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", help="逗号分隔 model（须有 settings/<m>.json）")
    ap.add_argument("--cases", default="all", help="逗号分隔用例 id，或 all")
    ap.add_argument("--k", type=int, default=None, help="覆盖每个用例的默认重复次数")
    ap.add_argument("--stamp", default="run", help="结果文件标签")
    ap.add_argument("--baseline", action="store_true", help="量基线快照并体检用例")
    ap.add_argument("--oracle", action="store_true", help="跑参考解自检")
    ap.add_argument("--self-check", action="store_true", help="重复判分测 flaky")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--judge", metavar="RESULTS_JSON", help="离线给开放题判分")
    ap.add_argument("--judge-check", action="store_true", help="考一考裁判自己")
    ap.add_argument("--report", nargs="+", metavar="RESULTS_JSON", help="把结果汇总成 markdown")
    ap.add_argument("--effort", metavar="VARIANT",
                    help="思考档位，走 opencode 的 --variant（取值由 provider 定，"
                         "如 minimal/high/max）。不传＝不加这个参数，用服务端配的档位。"
                         "★ 本机 llama-swap 的档位是服务端配的，传了未必生效 —— "
                         "做档位对照前先确认它真传下去了，别拿没生效的旋钮下结论")
    args = ap.parse_args()

    sel = select(args.cases)
    if args.baseline:
        raise SystemExit(cmd_baseline(sel))
    if args.oracle:
        raise SystemExit(cmd_oracle(sel))
    if args.self_check:
        raise SystemExit(cmd_self_check(sel, args.repeat))
    if args.judge_check:
        raise SystemExit(cmd_judge_check(sel))
    if args.judge:
        raise SystemExit(cmd_judge(Path(args.judge)))
    if args.report:
        raise SystemExit(cmd_report(args.report))
    if not args.models:
        ap.error("跑模型评测必须给 --models（或用 --baseline / --oracle / --self-check 自检）")
    raise SystemExit(cmd_run(args.models.split(","), sel, args.stamp, args.k, args.effort))


if __name__ == "__main__":
    main()
