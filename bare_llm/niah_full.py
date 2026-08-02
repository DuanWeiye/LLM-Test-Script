# 超长上下文 NIAH 全量：4 模型 × 4 长度 × 6 情景(各自深度)。前缀缓存复用，每长度仅一次 prefill。
import sys, json, os
SCRATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRATCH)
from niah_lib import build_doc, ask, NEEDLES

MODELS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["qwen3.6-35b-a3b"]
# 目标 token(实际以 prompt_n 为准)。注意造文长度按固定的 1.6 字符/token 估算(见 niah_lib)，
# 该系数随 tokenizer 而变——中文压缩率低的模型实际 token 会明显超出目标，可能撞上服务端 -c 上限报 400。
# NIAH_LENGTHS 可只补测指定档位(逗号分隔)，避免为了一档重跑全部；NIAH_TAG 可另存结果不覆盖已有。
LENGTHS = ([int(x) for x in os.environ["NIAH_LENGTHS"].split(",")]
           if os.environ.get("NIAH_LENGTHS") else [8000, 64000, 160000, 224000])
RESULTS = f"{SCRATCH}/niah_results{os.environ.get('NIAH_TAG', '')}.json"

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
                          "wall": r["wall"], "ans": r["ans"][:60],
                          "finish_reason": r.get("finish_reason"), "reasoning_len": r.get("reasoning_len")})
        actual = next((c.get("prompt_n") for c in cells if c.get("prompt_n")), "?")
        recall = sum(1 for c in cells if c.get("hit"))
        out[model][str(L)] = {"actual_tokens": actual, "recall": recall, "cells": cells}
        depth_str = " ".join(f"{int(c['depth']*100)}%{'✓' if c.get('hit') else '✗'}" for c in cells)
        print(f"  L目标{L//1000}K (实际{actual} tok): 召回 {recall}/6 | {depth_str}", flush=True)
        json.dump(out, open(RESULTS, "w"), ensure_ascii=False, indent=1)
print("\n=== NIAH 全部完成 ===", flush=True)
