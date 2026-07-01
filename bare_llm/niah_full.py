# 超长上下文 NIAH 全量：4 模型 × 4 长度 × 6 情景(各自深度)。前缀缓存复用，每长度仅一次 prefill。
import sys, json, os
SCRATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRATCH)
from niah_lib import build_doc, ask, NEEDLES

MODELS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["qwen3.6-35b-a3b"]
LENGTHS = [8000, 64000, 160000, 224000]   # 目标 token(实际以 prompt_n 为准)
RESULTS = f"{SCRATCH}/niah_results.json"

out = {}
for model in MODELS:
    print(f"\n########## {model} ##########", flush=True)
    out[model] = {}
    for L in LENGTHS:
        doc = build_doc(L)
        cells = []
        for idx, (depth, text, q, kw) in enumerate(NEEDLES):
            try:
                r = ask(model, doc, q)
            except Exception as e:
                cells.append({"depth": depth, "hit": False, "err": str(e)[:80]}); continue
            hit = any(k.lower() in r["ans"].lower() for k in kw)
            cells.append({"depth": depth, "hit": hit, "prompt_n": r["prompt_n"],
                          "wall": r["wall"], "ans": r["ans"][:60]})
        actual = next((c.get("prompt_n") for c in cells if c.get("prompt_n")), "?")
        recall = sum(1 for c in cells if c.get("hit"))
        out[model][str(L)] = {"actual_tokens": actual, "recall": recall, "cells": cells}
        depth_str = " ".join(f"{int(c['depth']*100)}%{'✓' if c.get('hit') else '✗'}" for c in cells)
        print(f"  L目标{L//1000}K (实际{actual} tok): 召回 {recall}/6 | {depth_str}", flush=True)
        json.dump(out, open(RESULTS, "w"), ensure_ascii=False, indent=1)
print("\n=== NIAH 全部完成 ===", flush=True)
