#!/usr/bin/env python3
"""LLM-judge：给开放式问答题（诊断类）判分，判的是**结论语义**而不是措辞。

**为什么换掉关键词 rubric**：关键词匹配绑的是措辞，不是结论。实测抓到过两类相反的错判 ——
一段完全正确的诊断因为写成「与信号**强弱**无关」（中间插了两个字）被判成漏答；
另一份没识别出触发条件的报告，却因为出现「## 建议执行**顺序**」这个无关小标题白拿一分。
每加一个新模型就要补一次关键词表，是典型的「验证器绑实现细节」。

**裁判用本机模型**（主人选定）。同源偏袒的风险用三件事压住：
  1. 判据写成结论描述，裁判只做「命中/未命中」的二值判断，没有打分自由度；
  2. 裁判看不到作者是谁，也不知道被评的是本机模型还是云端模型；
  3. **裁判自己要过自检**（`--judge-check`）：拿参考解、各种典型错误答案当 fixture，
     裁判必须判对才允许用它的结论 —— 裁判也要有 oracle，这和用例本身一个标准。

**离线批量跑**：评测阶段只保存全文，判分单独跑一遍。否则每判一次就要让 llama-swap
在被测模型和裁判模型之间热切换一次，既慢又干扰被测模型的计时。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

JUDGE_BASE = os.environ.get("JUDGE_BASE", "http://127.0.0.1:12345/v1")
JUDGE_KEY = os.environ.get("JUDGE_KEY", "")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen3.6-35b-a3b")


@dataclass
class Rubric:
    """一道开放题的判据。

    points    —— 该说到的结论，每条一分（→ F2P）
    negatives —— 不该得出的结论，出现即扣（→ P2P）
    """
    points: dict = field(default_factory=dict)
    negatives: dict = field(default_factory=dict)

    def keys(self):
        return list(self.points) + list(self.negatives)


PROMPT = """你在评阅一份技术分析报告。请逐条判断报告是否表达了下列每个要点。

判断标准：**只看结论和语义，不要求出现任何特定词句**。同义表述、换一种说法、拆成多句表达，
都算命中。反之，如果只是顺带提到某个词、并没有表达该要点的含义，就不算命中。

【该说到的要点】
{points}

【不该得出的结论】（报告若把它当成根本原因或解决方案，才算 true；只是提到并将其排除，算 false）
{negatives}

只输出一个 JSON 对象，不要任何解释文字，格式：
{{"points": {{"要点名": true/false, ...}}, "negatives": {{"项名": true/false, ...}}}}

===== 报告全文 =====
{report}
===== 全文结束 ====="""


def call(report: str, rubric: Rubric, model: str = None, timeout: int = 600) -> dict:
    """调裁判，返回 {"points": {...}, "negatives": {...}}。"""
    pts = "\n".join(f"- {k}：{v}" for k, v in rubric.points.items()) or "（无）"
    negs = "\n".join(f"- {k}：{v}" for k, v in rubric.negatives.items()) or "（无）"
    body = {
        "model": model or JUDGE_MODEL,
        "messages": [{"role": "user",
                      "content": PROMPT.format(points=pts, negatives=negs, report=report[:24000])}],
        "temperature": 0.0,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        f"{JUDGE_BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {JUDGE_KEY}"} if JUDGE_KEY else {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.load(resp)
    text = out["choices"][0]["message"]["content"] or ""
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError(f"裁判没返回 JSON：{text[:200]}")
    got = json.loads(text[s:e + 1])
    # 缺项按未命中处理，多余的键丢掉 —— 判分只认 rubric 里定义的项
    return {
        "points": {k: bool(got.get("points", {}).get(k, False)) for k in rubric.points},
        "negatives": {k: bool(got.get("negatives", {}).get(k, False)) for k in rubric.negatives},
    }


def to_verdict(judged: dict, rubric: Rubric):
    """裁判结论 → Verdict：要点计 F2P，否定项反过来计 P2P。"""
    from .verdict import Verdict
    v = Verdict()
    for k in rubric.points:
        v.f2p_add(bool(judged["points"].get(k)))
    for k in rubric.negatives:
        v.p2p_add(not bool(judged["negatives"].get(k)))
    hit = sum(1 for x in judged["points"].values() if x)
    bad = [k for k, x in judged["negatives"].items() if x]
    v.note(f"命中{hit}/{len(rubric.points)}"
           + (f" 错误结论:{','.join(bad)}" if bad else "")
           + " | " + ",".join(k for k, x in judged["points"].items() if x))
    return v


# ---------- 裁判自检 ----------
def check(fixtures: list, rubric: Rubric, model: str = None) -> tuple:
    """拿人工标注好的样本考裁判本身，返回 (逐项明细, 正确率)。

    fixtures: [{"name": ..., "text": ..., "points": {k: bool}, "negatives": {k: bool}}]
    """
    rows, n_ok, n_all = [], 0, 0
    for fx in fixtures:
        try:
            got = call(fx["text"], rubric, model=model)
        except Exception as ex:
            rows.append({"name": fx["name"], "error": str(ex)[:160]})
            continue
        wrong = []
        for k, want in fx.get("points", {}).items():
            n_all += 1
            if bool(got["points"].get(k)) == bool(want):
                n_ok += 1
            else:
                wrong.append(f"{k}(判{got['points'].get(k)}应{want})")
        for k, want in fx.get("negatives", {}).items():
            n_all += 1
            if bool(got["negatives"].get(k)) == bool(want):
                n_ok += 1
            else:
                wrong.append(f"!{k}(判{got['negatives'].get(k)}应{want})")
        rows.append({"name": fx["name"], "wrong": wrong,
                     "n_wrong": len(wrong)})
    return rows, (n_ok / n_all if n_all else 0.0)
