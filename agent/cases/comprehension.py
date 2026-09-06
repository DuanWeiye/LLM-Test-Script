#!/usr/bin/env python3
"""维度：长程理解 —— 读懂一摊代码/文档，把问题答对，而且**不动手改东西**。

这类题的 P2P 全是「不该做的事」：查个问题而已，不该顺手改文件。
"""
from __future__ import annotations

import re
from pathlib import Path

from core.verdict import Verdict

from . import Case

Q2_PROMPT = (
    "周报里那个「平均温度」到底是从哪儿算出来的？中间经了几道手？"
    "还有，读数缺失的时候它是怎么处理的？"
)


def check_q2(ctx) -> Verdict:
    """跨文件溯源：cli → report → （自己算的）→ reader 读进来的 Reading。

    这道题的正确答案里有个坑：周报的均温**不是**走 stats.average_temp，
    而是 report.py 自己又算了一遍，而且把缺失读数当 0。
    真读懂了的会点出这件事，只扫一眼 cli 的会答成 stats.average_temp。
    """
    r = ctx["result"]
    rl = r.lower()
    v = Verdict()
    v.f2p_add("report" in rl)                                    # 定位到 report 模块
    v.f2p_add("cli" in rl)                                       # 说清入口
    v.f2p_add("reader" in rl or "load" in rl or "csv" in rl)     # 数据从哪来
    v.f2p_add(bool(re.search(r"_mean_temp|mean_temp|自己(又)?算|单独实现|另算|重复实现", r)))
    # 缺失值处理：正确答案是「当成 0 计入」（这正是 R2 那个 bug）
    v.f2p_add(bool(re.search(r"当[作成]?\s*0|按\s*0|计为\s*0|算作\s*0|0\.0|视为\s*0", r)))
    d = ctx["diff"]
    v.p2p_add(not (d["added"] or d["modified"] or d["deleted"]))  # 只是问问题，别动手
    return v.note(f"命中 report={'report' in rl} 自己算={bool(re.search('_mean_temp|自己', r))} "
                  f"改动={d['modified'] or d['added'] or '无'}")


def or_q2(work: Path):
    return {"result":
            "链路是这样的：cli.py 的 report 子命令先用 reader.load() 把 CSV 读成 Reading 列表"
            "（温度字段为空时解析成 None），然后交给 report.build()。\n\n"
            "关键在于 build() 里的均温**不是**调 stats.average_temp，而是 report.py 自己写了一个 "
            "_mean_temp()。两者对缺失读数的处理不一样：stats.average_temp 会跳过 None，"
            "而 _mean_temp 把 None 当成 0.0 累加进分子、分母却照算全部条数。\n\n"
            "所以凡是丢过读数的设备，周报里的均温就会偏低 —— dev-a01 丢 1 条、dev-a06 丢 3 条，"
            "这两台和 avg 子命令的输出对不上，其余六台一致。", "tools": []}


# ---------- Q1：长文档综合 ----------
# 答案要跨三处才拼得出来：台账表（谁在 A 栋）、时间线（7 月之后动过固件的）、
# 以及一条回滚记录（gpu-03 装过 3.3.0-beta 当天回滚，当前仍是 3.2.0）。
# 干扰项齐全：B 栋也升级了两台、7/27 那次只动驱动没动固件、6/12 的基线升级在 7 月之前。
Q1_PROMPT = (
    "翻一下运维记录。A 栋那几台里，7 月之后动过固件的是哪几台？"
    "它们现在跑的分别是什么固件版本？"
)

_Q1_WANT = {"gpu-01": "3.2.1", "gpu-03": "3.2.0", "gpu-05": "3.2.0"}


def check_q1(ctx) -> Verdict:
    """三台都要点到、版本都要对，还不能被回滚记录和 B 栋的升级带偏。"""
    r = ctx["result"]
    v = Verdict()
    for dev in _Q1_WANT:
        v.f2p_add(dev in r)
    # 版本：3.2.1 是 gpu-01 独有的热修版本，3.2.0 是另外两台
    v.f2p_add("3.2.1" in r)
    v.f2p_add("3.2.0" in r)
    # 回滚陷阱：提到 3.3.0 可以，但必须是在说它被回滚了
    beta_ok = True
    if "3.3.0" in r:
        beta_ok = any(w in r for w in ("回滚", "退回", "撤回", "rollback", "已回退", "当天"))
    v.f2p_add(beta_ok)
    # 只动驱动那次不能算成固件升级
    v.f2p_add("560.35" not in r or "驱动" in r)

    # 不该把没动过的 gpu-07 说成升级了（提它「没动」是对的，所以要看语境）
    mislabeled = False
    for seg in re.split(r"[\n。；;]", r):
        if "gpu-07" in seg and re.search(r"升级|升到|动过|更新到", seg) \
                and not re.search(r"没|未|仍|保持|不在|排除|无", seg):
            mislabeled = True
    v.p2p_add(not mislabeled)
    d = ctx["diff"]
    v.p2p_add(not (d["added"] or d["modified"] or d["deleted"]))
    return v.note(f"点到={[d for d in _Q1_WANT if d in r]} 3.2.1={'3.2.1' in r} "
                  f"beta处理正确={beta_ok} 误标gpu-07={mislabeled}")


def or_q1(work: Path):
    return {"result":
            "A 栋一共四台：gpu-01、gpu-03、gpu-05、gpu-07。7 月之后动过固件的是其中三台：\n\n"
            "- **gpu-01** → 固件 3.2.1。7/19 半夜宕机后单独升的厂商热修版本，只有它是这个版本。\n"
            "- **gpu-03** → 固件 3.2.0。7/03 作为试点升到 3.2.0；7/25 试装过 3.3.0-beta，"
            "但当天因为偶发 ECC 报错就回滚回 3.2.0 了，所以现在仍是 3.2.0。\n"
            "- **gpu-05** → 固件 3.2.0。8/01 升的。\n\n"
            "gpu-07 从 6/12 拉齐基线之后就没再动过固件，仍是 3.1.0。\n\n"
            "另外两点别混：7/03 试点里的 gpu-04 和 8/01 的 gpu-06 都在 B 栋，不在问的范围里；"
            "7/27 那次全机房动的是驱动（560.35），固件没动。", "tools": []}


CASES = [
    Case(id="Q1", dim="长程理解", suite="ops_scripts", prompt=Q1_PROMPT,
         k=3, check=check_q1, oracle=or_q1,
         notes="答案跨台账表+时间线+回滚记录三处；干扰项有 B 栋升级、只动驱动那次、beta 回滚"),
    Case(id="Q2", dim="长程理解", suite="metrics_cli", prompt=Q2_PROMPT,
         k=3, check=check_q2, oracle=or_q2,
         notes="坑在周报自己又算了一遍均温；只扫 cli 的会答成 stats.average_temp"),
]
