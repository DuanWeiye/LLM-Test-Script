# NIAH 公共库：造含 6 情景针 + 大量相似干扰项的长文；前缀缓存复用。
import os, json, time, urllib.request
BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:12345/v1").rstrip("/") + "/chat/completions"

# 6 个情景针：(depth 占比, 文本, 问题, 命中关键词)
NEEDLES = [
 (0.05, "【机密】东京数据中心的主访问码是 VIOLET-7492，仅限管理员使用。",
        "东京数据中心的主访问码是什么？", ["7492", "violet"]),
 (0.20, "【人事】项目代号 Phoenix 的总负责人是 佐藤美咲 部长。",
        "项目代号 Phoenix 的总负责人是谁？", ["佐藤美咲", "佐藤"]),
 (0.40, "【通知】全球服务器迁移的最终截止日期定为 2027年3月14日，不得延期。",
        "全球服务器迁移的最终截止日期是哪一天？", ["3月14", "2027年3月14", "3/14"]),
 (0.60, "【库存】京都第7号仓库的库存上限被设定为 8350 箱。",
        "京都第7号仓库的库存上限是多少箱？", ["8350"]),
 (0.80, "[Policy] The API rate limit for the Osaka cluster is 4096 requests per minute.",
        "What is the API rate limit (requests per minute) for the Osaka cluster? Answer with the number.", ["4096"]),
 (0.95, "【应急】公司应急保险柜的开启口令是 蓝鲸归航1988。",
        "公司应急保险柜的开启口令是什么？", ["1988", "蓝鲸"]),
]

# 干扰项模板：与针同款句式但用别的实体/数值(刻意避开针的关键词值)
_CITIES = ["大阪","柏林","名古屋","里昂","西雅图","开罗","孟买","赫尔辛基","布拉格","里斯本","墨尔本","多伦多"]
_CODES = ["Hydra","Griffin","Kraken","Pegasus","Sphinx","Chimera","Titan","Orion"]
_NAMES = ["田中一郎","铃木花子","高桥健","渡边修","山本绫","中村航"]
_COLORS = ["CRIMSON","AMBER","INDIGO","TEAL","OLIVE","MAROON"]

def _filler(i):
    t = i % 6
    if t == 0:  # 别的城市数据中心访问码(避开 7492/VIOLET)
        return f"备忘录#{i}：{_CITIES[i%len(_CITIES)]}数据中心的访问码是 {_COLORS[i%len(_COLORS)]}-{5000+i%900}。"
    if t == 1:  # 别的项目负责人(避开 佐藤美咲)
        return f"备忘录#{i}：项目代号 {_CODES[i%len(_CODES)]} 的负责人是 {_NAMES[i%len(_NAMES)]}。"
    if t == 2:  # 别的日期(避开 3月14)
        return f"备忘录#{i}：{_CITIES[i%len(_CITIES)]}分部的审计日期是 2026年{1+i%12}月{1+i%27}日。"
    if t == 3:  # 别的库存(避开 8350)
        return f"备忘录#{i}：{_CITIES[i%len(_CITIES)]}第{1+i%9}号仓库的库存上限是 {5100+i%800} 箱。"
    if t == 4:  # 别的限流(避开 4096)
        return f"Memo#{i}: The rate limit for the {_CITIES[i%len(_CITIES)]} cluster is {1024+ (i%3)*1000} requests per minute."
    return f"备忘录#{i}：{_CITIES[i%len(_CITIES)]}办公室的午休时间为 12:{(i%6)*10:02d}。"

def build_doc(target_tokens):
    """造长文：填充+干扰，把 6 个针插到各自深度。返回文档字符串(不含问题)。"""
    target_chars = int(target_tokens * 1.6)  # 冒烟实测 ~1.6 字符/token(让 label≈实际 token)
    lines, i = [], 0
    while sum(len(x) for x in lines) < target_chars:
        lines.append(_filler(i)); i += 1
    for depth, text, _, _ in NEEDLES:
        pos = min(int(len(lines) * depth), len(lines) - 1)
        lines.insert(pos, text)
    return "\n".join(lines)

_SYS = "你是检索助手。只输出被问到的那个具体值本身（一个词/数字/日期/口令），不要任何前缀、解释或出处说明（不要写“根据备忘录…”）。"

def ask(model, doc, question, max_tokens=120):
    content = doc + "\n\n问题：" + question
    body = json.dumps({"model": model, "messages": [
                           {"role": "system", "content": _SYS},
                           {"role": "user", "content": content}],
                       "max_tokens": max_tokens, "temperature": 0,
                       "cache_prompt": True}).encode()
    req = urllib.request.Request(BASE, body, {"Content-Type": "application/json"})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=1200))
    wall = time.time() - t0
    t = d.get("timings", {})
    return {"prompt_n": t.get("prompt_n"), "prefill_tps": t.get("prompt_per_second"),
            "wall": round(wall, 1), "ans": d["choices"][0]["message"]["content"].strip()}
