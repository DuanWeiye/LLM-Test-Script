#!/usr/bin/env python3
"""维度：向后兼容 —— 用户提的是新需求，没提的老约定能不能守住。

真实事故里最常见的一类：新功能做出来了，老调用方悄悄挂了。
（原型之一取自本机 audioServer 的一次回归：翻译原本靠「语言对」自动定向，
新端点却退化成必须显式指定 source/target，是在 ESP32 侧实装时才发现的。）

这一维度的判分有个天然的好处：**兼容性根本不用单独写 F2P** ——
「老写法本来就能用」在基线里就是绿的，基线快照会自动把它归进 P2P。
模型只顾着做新需求、把老路径改坏，P2P 立刻红。
"""
from __future__ import annotations

from pathlib import Path

from . import Case

# ---------- B2：配置项改名 ----------
B2_PROMPT = (
    "阈值配置里那些名字太隐晦了，warn_c、crit_c 谁看得懂是什么意思。"
    "给我改成一看就明白的。"
)


def or_b2(work: Path):
    """参考解：改成描述性名字，同时保留对老键名的兼容读取。

    用户没提兼容，但现场设备上跑的还是老配置文件 —— 读不到就静默用默认值，
    等于把线上告警阈值悄悄改掉了。
    """
    (work / "config" / "thresholds.ini").write_text(
        "[temperature]\n"
        "; GPU 温度告警阈值（摄氏度）\n"
        "warning_celsius = 78\n"
        "critical_celsius = 88\n"
        "hysteresis_celsius = 2\n"
        "\n"
        "[utilization]\n"
        "warning_percent = 95\n", encoding="utf-8")

    p = work / "watch_gpu.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        '    tp = configparser.ConfigParser()\n'
        '    tp.read(Path(__file__).parent / ref, encoding="utf-8")\n'
        '    return tp.getfloat("temperature", "warn_c", fallback=80.0)',
        '    tp = configparser.ConfigParser()\n'
        '    tp.read(Path(__file__).parent / ref, encoding="utf-8")\n'
        '    # 新名字优先；现场那批设备上还是老配置文件，老键名要继续认\n'
        '    for key in ("warning_celsius", "warn_c"):\n'
        '        if tp.has_option("temperature", key):\n'
        '            return tp.getfloat("temperature", key)\n'
        '    return 80.0')
    p.write_text(src, encoding="utf-8")


# ---------- B1：单位对自动定向 ----------
# 原型是本机 audioServer 2026-06 的一次真实回归：翻译本来靠「语言对」自动定向，
# 新端点退化成必须显式指定 source/target，把老调用方全弄挂了。
B1_PROMPT = (
    "这个换算服务每次都得同时告诉它从什么单位换到什么单位，太啰嗦了。"
    "我们的场景是固定一对单位来回换：给它摄氏就该出华氏，给华氏就该出摄氏。\n"
    "上游会这么传过来：`{\"value\": 100, \"src\": \"C\", \"pair\": [\"C\", \"F\"]}` —— 没有 dst。\n"
    "你支持一下。怎么实现你定，但老的带 dst 的调用还在别处跑着，不能坏。"
)


def or_b1(work: Path):
    """参考解：服务层按单位对推方向，显式 dst 优先；底层 convert 一个字没动。"""
    (work / "service.py").write_text('''"""对外的换算服务入口。"""
from __future__ import annotations

from converter import convert


def _resolve_target(src: str, payload: dict) -> str:
    """定出这次要换到哪个单位。

    显式给了 dst 就用 dst；否则按单位对推方向 —— 输入等于其中一个，就换成另一个。
    """
    dst = payload.get("dst")
    if dst is not None:
        return dst
    pair = payload.get("pair")
    if not pair or len(pair) != 2:
        raise ValueError("请求里既没有 dst，也没有可用的单位对 pair")
    a, b = pair
    if src == a:
        return b
    if src == b:
        return a
    raise ValueError(f"单位 {src} 不属于单位对 {list(pair)}")


def handle(payload: dict) -> dict:
    """处理一条换算请求。

    老写法（带 dst）行为保持不变；新写法给一个单位对 pair，方向由输入单位自动决定。
    """
    value = payload["value"]
    src = payload["src"]
    target = _resolve_target(src, payload)
    return {"value": convert(value, src, target), "unit": target}
''', encoding="utf-8")


# ---------- B3：把旧文件并进新存储 ----------
B3_PROMPT = (
    "notes/personal.txt 里那些东西挪到新的记忆库里去吧，以后就不留那个文件了。"
    "别给我弄丢东西。"
)


def or_b3(work: Path):
    """参考解：剥掉日期前缀后逐条加入（Store.add 自带去重），再删掉旧文件。"""
    import json
    import re as _re

    old = work / "notes" / "personal.txt"
    items = json.loads((work / "data" / "store.json").read_text(encoding="utf-8"))
    seen = {it["text"] for it in items}
    for line in old.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        # 「2026-05-02 住在……」→ 去掉日期前缀，同内容不同日期才不会被当成两条
        text = _re.sub(r"^\d{4}-\d{2}-\d{2}\s+", "", line).strip()
        if text and text not in seen:
            seen.add(text)
            items.append({"text": text, "source": "personal.txt"})
    (work / "data" / "store.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    old.unlink()
    return {"result": "已把 personal.txt 里的 5 条独立内容并进记忆库（重复的和只有日期不同的"
                      "各合成一条），原有 2 条保持不动，旧文件已删除。"}


CASES = [
    Case(id="B3", dim="向后兼容", suite="note_store", prompt=B3_PROMPT,
         k=3, hidden="B3", oracle=or_b3,
         notes="取材 agent 把 user.txt 并进共通记忆；「别覆盖已有条目」用户没提，由 P2P 守住"),
    Case(id="B1", dim="向后兼容", suite="unit_service", prompt=B1_PROMPT,
         k=3, hidden="B1", oracle=or_b1,
         notes="取材 audioServer 真实回归；老 payload 在基线里就是绿的 → 自动进 P2P"),
    Case(id="B2", dim="向后兼容", suite="ops_scripts", prompt=B2_PROMPT,
         k=3, hidden="B2", oracle=or_b2,
         notes="用户没提兼容，老配置文件能不能继续读由 P2P 自动守住"),
]
