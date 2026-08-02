#!/usr/bin/env python3
"""把两套评测的结果汇总成一份给人看的 markdown 报告。

用法：
    python3 make_report.py  [-o 输出文件]

自己去 bare_llm/ 和 claude_code/results/ 找结果文件，按模型对齐成表。
裸卷成绩是「过了几次/总次数」，agent 卷是 `pass@1 (partial 均值)`。
"""
from __future__ import annotations

import argparse
import glob

import json
import os
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BARE = os.path.join(HERE, "bare_llm")
CC = os.path.join(HERE, "claude_code", "results")

# 模型 → 本轮结果文件的 tag。**必须精确指定**：早期温度 0 那轮的文件名
# （ab_results_hardqwen36.json）会被 `ab_results_*.json` 这种通配一并匹配到，
# 混进来就是拿两种采样条件的数字凑一张表 —— 不可比。
MODEL_TAG = {
    "qwen3.6-35b-a3b": "_qwen36a3b",
    "qwen3.6-35b-uncensored": "_uncensored",
    "laguna-s-2.1": "_laguna",
    "deepseek-v4-flash": "_dsflash",
}

# 维度显示名与顺序
BARE_DIMS = OrderedDict([
    ("code", "编码(三语)"), ("tool", "工具判断"), ("fact", "事实"), ("format", "格式遵循"),
    ("hardcode", "硬算法"), ("reason", "多步推理"), ("knowledge", "知识广度"),
    ("instruct", "多约束指令"),
])
OPEN_DIMS = {"halluc": "抗幻觉(盲评)", "breadth": "广度(盲评)"}


def _load(paths):
    """读一批结果文件，合并成 {model: {case_id: rec}}。"""
    out = defaultdict(dict)
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for model, cases in data.items():
            out[model].update(cases)
    return out


def _bare_paths(models, kind=""):
    """本轮各模型的裸卷结果路径。kind='_hard' 取难卷。"""
    return [os.path.join(BARE, f"ab_results{kind}{MODEL_TAG[m]}.json")
            for m in models if m in MODEL_TAG]


def _rate(rec):
    """一条用例的通过率与「几/几」文本。pass 可能是次数(新版)或 bool(旧版)。"""
    p, n = rec.get("pass"), rec.get("n")
    if p is None:
        return None, None                      # 盲评题，不自动判分
    if isinstance(p, bool):
        return (1.0 if p else 0.0), ("1/1" if p else "0/1")
    n = n or 1
    return (p / n if n else 0.0), f"{p}/{n}"


def bare_section(models):
    """裸卷：常规卷 + 难卷合并成一张维度表 + 一张失分明细表。"""
    normal = _load(_bare_paths(models))
    hard = _load(_bare_paths(models, "_hard"))
    merged = defaultdict(dict)
    for src in (normal, hard):
        for m, cases in src.items():
            merged[m].update(cases)

    lines = []
    have = [m for m in models if m in merged]
    if not have:
        return ["_（没有找到裸卷结果）_", ""]

    # 维度汇总
    lines += ["| 维度 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    for dim, label in BARE_DIMS.items():
        row = [label]
        for m in have:
            got = tot = 0
            for cid, rec in merged[m].items():
                if rec.get("dim") != dim:
                    continue
                r, _ = _rate(rec)
                if r is None:
                    continue
                p, n = rec.get("pass"), rec.get("n") or 1
                got += p if not isinstance(p, bool) else int(p)
                tot += n if not isinstance(p, bool) else 1
            row.append(f"{got}/{tot}" + (f" ({got/tot:.0%})" if tot else ""))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 失分明细：任何模型没拿满的题都列出来
    lines += ["**没拿满分的题**（空白＝该模型满分）", "",
              "| 题 | 考点 | " + " | ".join(have) + " |", "|---|---|" + "---|" * len(have)]
    all_ids = OrderedDict()
    for m in have:
        for cid in merged[m]:
            all_ids.setdefault(cid, merged[m][cid].get("dim"))
    for cid, dim in all_ids.items():
        cells, imperfect = [], False
        for m in have:
            rec = merged[m].get(cid)
            if not rec:
                cells.append("—")
                continue
            r, txt = _rate(rec)
            if r is None:
                cells.append("盲评")
                continue
            cells.append(txt if r < 1.0 else "")
            if r < 1.0:
                imperfect = True
        if imperfect:
            lines.append(f"| {cid} | {BARE_DIMS.get(dim, OPEN_DIMS.get(dim, dim))} | "
                         + " | ".join(cells) + " |")
    lines.append("")
    return lines


def cc_section(models):
    """agent 卷：逐用例 + 逐维度。"""
    # 同样按 tag 精确读：早期那轮（C1 改名前）的 results_qwen36.json 不该混进来
    data = _load([os.path.join(CC, f"results{MODEL_TAG[m]}.json")
                  for m in models if m in MODEL_TAG])
    have = [m for m in models if m in data]
    if not have:
        return ["_（没有找到 agent 卷结果）_", ""]

    order, dims = [], OrderedDict()
    for m in have:
        for cid, rec in data[m].items():
            if cid not in order:
                order.append(cid)
                dims[cid] = rec.get("dim", "")

    lines = ["| 用例 | 维度 | " + " | ".join(have) + " |", "|---|---|" + "---|" * len(have)]
    for cid in order:
        row = [cid, dims.get(cid, "")]
        for m in have:
            rec = data[m].get(cid)
            if not rec:
                row.append("—")
                continue
            p1 = rec.get("pass_at_1")
            pm = rec.get("partial_mean")
            row.append("—" if p1 is None else f"{p1:.2f} ({pm:.2f})")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 维度汇总
    by_dim = OrderedDict()
    for cid in order:
        by_dim.setdefault(dims.get(cid, ""), []).append(cid)
    lines += ["| 维度 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    for dim, cids in by_dim.items():
        row = [dim]
        for m in have:
            recs = [data[m][c] for c in cids if c in data[m] and data[m][c].get("pass_at_1") is not None]
            if not recs:
                row.append("—")
                continue
            p1 = sum(r["pass_at_1"] for r in recs) / len(recs)
            pm = sum(r["partial_mean"] for r in recs) / len(recs)
            row.append(f"{p1:.2f} ({pm:.2f})")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 行为观察
    lines += ["**行为观察**", "",
              "| 模型 | 总运行 | 平均工具数 | 平均耗时 | 中断 | 判分器故障 |", "|---|---|---|---|---|---|"]
    for m in have:
        runs = [r for rec in data[m].values() for r in rec.get("runs", [])]
        if not runs:
            continue
        n = len(runs)
        tools = sum(r.get("n_tools", 0) for r in runs) / n
        wall = sum(r.get("wall", 0) for r in runs) / n
        ab = sum(1 for r in runs if r.get("aborted"))
        ge = sum(1 for r in runs if r.get("grader_error"))
        lines.append(f"| {m} | {n} | {tools:.1f} | {wall:.0f}s | {ab} | {ge} |")
    lines.append("")
    return lines


def niah_section(models):
    """NIAH：{model: {长度档: {actual_tokens, recall, cells:[{depth,hit,...}]}}}。

    本地那几个跑在 niah_results.json，走别的 endpoint 的（云端）用 NIAH_TAG 另存，
    这里把所有 niah_results*.json 合起来读。
    """
    data = {}
    for path in sorted(glob.glob(os.path.join(BARE, "niah_results*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for m, v in d.items():
            data.setdefault(m, {}).update(v)
    have = [m for m in models if m in data]
    if not have:
        return ["_（没有找到 NIAH 结果）_", ""]

    buckets = []
    for m in have:
        for b in data[m]:
            if b not in buckets:
                buckets.append(b)
    buckets.sort(key=lambda x: int(x))

    lines = ["每档 6 根针（深度 5%/20%/40%/60%/80%/95%），格子是召回数。", "",
             "| 长度档 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    failed = []
    for b in buckets:
        row = [f"{int(b)//1000}K"]
        for m in have:
            cell = data[m].get(b)
            if not cell:
                row.append("—")
                continue
            cells = cell.get("cells", [])
            errs = [c for c in cells if c.get("err")]
            # 整档全是请求错误 ≠ 模型没召回。多半是造文按固定字符/token 估算，
            # 中文压缩率低的 tokenizer 实际 token 冲破了服务端 -c 上限（HTTP 400）。
            if cells and len(errs) == len(cells):
                row.append("**请求失败**")
                failed.append((m, b, errs[0].get("err", "")[:40]))
            else:
                row.append(f"{cell['recall']}/6")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    if failed:
        lines.append("> **注意**：标「请求失败」的格子是**请求没发成功**，不是模型没召回 —— "
                     "不能当成长上下文能力弱来读。")
        for m, b, err in failed:
            lines.append(f"> - {m} 在 {int(b)//1000}K 档：`{err}`"
                         f"（该模型 tokenizer 对中文压缩率低，实际 token 冲破了上下文上限）")
        lines.append("")

    # 实际 token 数：档位标签只是目标值，不同 tokenizer 差很多
    lines += ["实际 prompt token 数（档位标签只是目标，中文压缩率因 tokenizer 而异）：", "",
              "| 长度档 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    for b in buckets:
        row = [f"{int(b)//1000}K"]
        for m in have:
            cell = data[m].get(b)
            row.append(str(cell.get("actual_tokens", "?")) if cell else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 哪个深度最容易丢
    lines += ["按深度看（所有档位累计命中/尝试）：", "",
              "| 深度 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    depths = [0.05, 0.20, 0.40, 0.60, 0.80, 0.95]
    for d in depths:
        row = [f"{int(d*100)}%"]
        for m in have:
            hit = tot = 0
            for b in data[m].values():
                for c in b.get("cells", []):
                    if abs(c.get("depth", -1) - d) < 1e-6:
                        tot += 1
                        hit += 1 if c.get("hit") else 0
            row.append(f"{hit}/{tot}" if tot else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "RESULTS.md"))
    ap.add_argument("--models", default="qwen3.6-35b-a3b,qwen3.6-35b-uncensored,"
                                        "laguna-s-2.1,deepseek-v4-flash")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    out = ["# 评测结果", "",
           "两套卷子、同一批模型。裸卷考模型自己会什么，agent 卷考把活交给它能不能干成。", "",
           "- **裸卷**：不指定采样参数，按各模型官方推荐设定跑；每题 3 次，成绩记「过了几次/3」。",
           "- **agent 卷**：Claude Code 当统一外壳只换 endpoint；格子是 `pass@1 (partial 均值)`，",
           "  pass@1 是全或无（F2P 全过且 P2P 一条没坏），partial 是检查项通过比例。", "",
           "---", "", "## 一、裸卷", ""]
    out += bare_section(models)
    out += ["---", "", "## 二、Agent 卷（Claude Code 外壳）", ""]
    out += cc_section(models)
    out += ["---", "", "## 三、超长上下文（NIAH）", ""]
    out += niah_section(models)

    open(args.out, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("报告写入", args.out)


if __name__ == "__main__":
    main()
