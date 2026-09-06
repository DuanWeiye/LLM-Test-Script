#!/usr/bin/env python3
"""长上下文推理卷（LR1~LR4）。2026-09-06 新增，用来接替已饱和退役的 NIAH。

**为什么 NIAH 不够用了**：纯检索式的大海捞针，全部模型在 4 个长度档 × 6 个深度上
**全部 6/6 命中**，零区分度 —— 「能不能从长文里捞出一个值」这件事已经不是挑战了。

本卷换一个问法：**光捞出来没用，得把捞到的几条组合起来才能作答**。

  LR1  两跳     设备 → 在哪栋楼 → 那栋楼的维护窗口
  LR2  三跳+算  当前采样间隔（被改过）× 连续超阈次数 = 最短告警耗时
  LR3  变量追踪 配置项改过三次且**记录在文档里是日期乱序的**（台账按设备分组不按时间排），
               末尾还有一条「日期更晚但尚未生效」的计划值
  LR4  后文修正 前面说三台都升级了，后面说其中一台回滚了

四道题的针**混在同一篇台账里**（跟真实的运维台账一样），问不同的问题时前缀缓存可复用，
一个长度档只 prefill 一次。实体名字刻意错开（TR-8842 / CL-31 / AG-77 / GW-0x），
免得题目之间互相制造歧义。

干扰项与针同款句式、同款量级，所以蒙不出来：楼栋维护窗口有十几个、
采样间隔有一堆、阈值变更记录也有一堆。
"""
import os
import re

from eval_lib import apply_sampling, post
from niah_lib import _filler

# 文档长度（目标 token）。不必像 NIAH 那样跑 4 个档位，但**长度本身就是难度**：
# 实测同一批题，33K 时 LR1 是 3/3，134K 时掉到 2/3。默认取 128K，
# 要压更长或图快可以用 LONGCTX_TOKENS 调。
TARGET_TOKENS = int(os.environ.get("LONGCTX_TOKENS", "128000"))

# 针：(depth, text)。同一题的两条针刻意放在文档的两端，逼它真的跨距离组合，
# 而不是靠局部窗口连蒙带猜。
LONG_NEEDLES = [
    (0.08, "【台账】网关 TR-8842 部署在 B 栋 3 层机房。"),
    (0.88, "【变更】2026-03-01 汇聚节点 AG-77 的上报阈值设为 70。"),
    (0.22, "【台账】采集器 CL-31 的采样间隔是 15 秒。"),
    (0.55, "【变更】2026-06-10 起采集器 CL-31 的采样间隔改为 20 秒。"),
    (0.35, "【运维】固件 2.6.1 已完成灰度，GW-01、GW-02、GW-03 三台全部升级到位。"),
    (0.48, "【变更】2026-05-12 汇聚节点 AG-77 的上报阈值调整为 75。"),
    (0.61, "【规则】CL-31 所属的 A 组，告警需要连续 4 个采样点超过阈值才触发。"),
    (0.74, "【排期】B 栋的维护窗口是每周二 02:00-04:00，其它时段不得停机。"),
    (0.86, "【故障】GW-02 因电源模块故障已回滚到 2.5.8，暂不重新升级。"),
    (0.15, "【变更】2026-07-20 汇聚节点 AG-77 的上报阈值调整为 78。"),
    (0.97, "【计划】2026-09-01 起拟将 AG-77 的上报阈值调整为 82，该变更尚在审批中、目前未生效。"),
]

_BUILDINGS = ["A", "C", "D", "E", "F", "G"]
_WEEKDAYS = ["周一", "周三", "周四", "周五", "周六", "周日"]


def _filler_ops(i):
    """运维台账风格的干扰项：和四道题的针同款句式、同款量级。

    没有这些，模型光靠「文档里只有一个星期几」就能蒙对 LR1。
    """
    t = i % 5
    if t == 0:
        return (f"【排期】{_BUILDINGS[i % len(_BUILDINGS)]} 栋的维护窗口是每{_WEEKDAYS[i % len(_WEEKDAYS)]} "
                f"{(i % 5) + 20:02d}:00-{(i % 5) + 22:02d}:00。")
    if t == 1:
        return f"【台账】采集器 CL-{40 + i % 50} 的采样间隔是 {5 + (i % 8) * 5} 秒。"
    if t == 2:
        return (f"【变更】2026-{1 + i % 9:02d}-{1 + i % 27:02d} 汇聚节点 AG-{10 + i % 60} "
                f"的上报阈值调整为 {60 + i % 35}。")
    if t == 3:
        return f"【台账】网关 TR-{8000 + i % 800} 部署在 {_BUILDINGS[i % len(_BUILDINGS)]} 栋 {1 + i % 6} 层机房。"
    return (f"【规则】CL-{40 + i % 50} 所属的 {chr(66 + i % 5)} 组，"
            f"告警需要连续 {2 + i % 6} 个采样点超过阈值才触发。")


def build_long_doc(target_tokens=None):
    """造台账长文并把针插到各自深度。与 niah_lib.build_doc 同构，只是干扰项换成运维口径。"""
    target_chars = int((target_tokens or TARGET_TOKENS) * 1.6)   # 同 niah_lib：~1.6 字符/token
    lines, i = [], 0
    while sum(len(x) for x in lines) < target_chars:
        # 两种干扰交替：一半是 NIAH 那套通用备忘录，一半是本卷的运维台账句式
        lines.append(_filler_ops(i) if i % 2 else _filler(i))
        i += 1
    for depth, text in LONG_NEEDLES:
        pos = min(int(len(lines) * depth), len(lines) - 1)
        lines.insert(pos, text)
    return "\n".join(lines)


# 提问 -------------------------------------------------------------------

# NIAH 那句 system（「只输出被问到的那个具体值本身」）在这里不能用：
# 本卷问的是要推一步才有的结论，逼它只吐一个值反而会把「先算一下」的空间掐掉。
_SYS = ("你是运维助手。依据给出的台账内容回答问题。台账里可能有多条相关记录，"
        "注意时间先后与后文对前文的修正。回答要简洁，不要复述台账原文。")


def ask_long(model, doc, question, max_tokens=400, seed=0):
    """发一次长上下文提问。doc 放在前面，问题接在后面 —— 顺序固定，
    同一篇文档问不同问题时前缀缓存才能命中，一个长度档只 prefill 一次。"""
    body = apply_sampling({"model": model,
                           "messages": [{"role": "system", "content": _SYS},
                                        {"role": "user", "content": doc + "\n\n问题：" + question}],
                           "max_tokens": max_tokens, "cache_prompt": True})
    if seed:
        body["seed"] = seed
    d = post(body, timeout=1200)
    msg = d["choices"][0]["message"]
    tm = d.get("timings") or {}
    usage = d.get("usage") or {}
    # ⚠ 两个数字含义不同，别混用：llama.cpp 的 `timings.prompt_n` 是**本次实际处理**的
    #   prompt token 数，前缀缓存命中的部分不计 —— 同一篇文档问第二个问题时它只有几百，
    #   拿它当「文档多长」会严重低估（实测 33K 的文档第二问只报 511）。
    #   要看文档真实长度得用 `usage.prompt_tokens`。
    #   （NIAH 卷用的是「取第一个非空的 prompt_n」，第一问必然全量 prefill，所以侥幸没错。）
    return {"ans": (msg.get("content") or "").strip(),
            "prompt_n": tm.get("prompt_n"),
            "prompt_total": usage.get("prompt_tokens"),
            "finish_reason": d["choices"][0].get("finish_reason"),
            "reasoning_len": len(msg.get("reasoning_content") or "")}


# 判分 -------------------------------------------------------------------

def _lr1(ans):
    """B 栋的窗口是周二 02:00。答周二且带 02 才算——只答「周二」不给时间不算完整。"""
    ok = ("周二" in ans or "火曜" in ans or "Tuesday" in ans.lower()) and re.search(r"\b0?2[:：]0?0", ans)
    return bool(ok), f"ans={ans[:60]!r}"


def _lr2(ans):
    """三跳：采样间隔被改过（15→20），当前值 20 秒 × 连续 4 点 = 80 秒。

    答 60 说明用的是**旧的**采样间隔（15×4）——变量追踪没做，只做了检索。
    这个错误值单独标出来，比笼统记一个「错」有用得多。
    """
    nums = re.findall(r"\d+", ans)
    stale = "60" in nums
    return ("80" in nums and not stale), f"数字={nums[:5]} 用了旧间隔={stale}"


def _lr3(ans):
    """当前生效值 78。两类错都要抓出来：

      70/75 —— 抓到的是**旧值**，变量追踪失败
      82    —— 抓到的是**尚未生效**的计划值，没读出「审批中、未生效」这层
    """
    nums = re.findall(r"\d+", ans)
    stale = [x for x in ("70", "75") if x in nums]
    future = "82" in nums
    return ("78" in nums and not stale and not future), \
           f"数字={nums[:5]} 旧值={stale or '无'} 误用未生效值={future}"


def _lr4(ans):
    """当前跑 2.6.1 的是 GW-01 和 GW-03。GW-02 回滚了，答案里出现它就是没读到后文的修正。"""
    up = re.findall(r"GW-?0?(\d)", ans.upper())
    has13 = "1" in up and "3" in up
    has2 = "2" in up
    return (has13 and not has2), f"提到的机器={sorted(set(up))} ans={ans[:60]!r}"


# (id, lang, question, grade, max_tokens)
# max_tokens 给得比 NIAH（120）宽：这些题要推理，掐太死会把「算到一半被截断」记成答错。
LONG_CASES = [
    ("LR1", "CN", "网关 TR-8842 要做停机维护的话，可以安排在什么时候？"
                  "回答星期几和具体时间段即可。", _lr1, 400),
    ("LR2", "CN", "按当前配置，采集器 CL-31 从第一个采样点超阈值开始算，"
                  "最快多少秒会触发一次告警？只回答秒数。", _lr2, 400),
    ("LR3", "CN", "汇聚节点 AG-77 当前生效的上报阈值是多少？只回答数字。", _lr3, 300),
    ("LR4", "CN", "现在哪几台 GW 设备正在运行固件 2.6.1？只列设备编号。", _lr4, 300),
]
