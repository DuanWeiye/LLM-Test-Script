# 难卷 A/B：四模型，思考全程关(不传 enable_thinking=服务端默认关)。
# 专挑能拉开差距的题：硬算法/多步推理/更广知识/多约束指令/更难工具/广度。
import sys, json, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_lib import (chat, extract_code, run_code, run_code_verdict, grade_tool,
                      repeat_chat, repeat_turns, contains_kw, REPEAT, SEED_BASE,
                      TOOLS, SCRATCH)
from cases_hard import HARD    # 保留的高难单函数题 X1~X6，与 HC 同格式
from cases_multi import MULTI  # 多轮一致性 MT1~MT4（2026-09-06 新增）
from cases_longctx import (build_long_doc, ask_long, LONG_CASES,  # 长上下文推理 LR1~LR4
                           TARGET_TOKENS)
from cases_conflict import CONFLICT  # 约束冲突 IFC1~IFC4（含无冲突对照组）

MODELS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["qwen3.6-35b-a3b"]
TAG = sys.argv[2] if len(sys.argv) > 2 else ""
RESULTS = f"{SCRATCH}/ab_results_hard{TAG}.json"
JUDGE = f"{SCRATCH}/ab_judge_queue_hard{TAG}.json"

# ---------- 硬编码（exec 判分；id, lang, prompt, test, forbid 子串可选）----------
HC = [
 ("HC1","EN","`def length_of_lis(nums):` 返回最长严格递增子序列的长度(尽量 O(n log n))。只给代码。",
  "assert length_of_lis([10,9,2,5,3,7,101,18])==4\nassert length_of_lis([])==0\nassert length_of_lis([7,7,7])==1",None),
 ("HC2","CN","实现 `def edit_distance(a, b):` 计算两个字符串的 Levenshtein 编辑距离。只给代码。",
  "assert edit_distance('horse','ros')==3\nassert edit_distance('','abc')==3\nassert edit_distance('abc','abc')==0",None),
 ("HC3","EN","Fix the bug in this binary search (it can loop forever / miss). Return `def bsearch(arr, x):` index or -1.\n```python\ndef bsearch(arr,x):\n    lo,hi=0,len(arr)\n    while lo<hi:\n        m=(lo+hi)//2\n        if arr[m]==x: return m\n        elif arr[m]<x: lo=m\n        else: hi=m\n    return -1\n```",
  "assert bsearch([1,3,5,7,9],7)==3\nassert bsearch([1,3,5],4)==-1\nassert bsearch([1],1)==0\nassert bsearch([],5)==-1",None),
 ("HC4","CN","实现 `def calc(expr):` 计算只含 + - * / 和括号的算术字符串，遵守优先级，返回数值。**禁止使用 eval/exec**，要自己解析。只给代码。",
  "assert calc('2+3*4')==14\nassert calc('(2+3)*4')==20\nassert abs(calc('10/4')-2.5)<1e-9\nassert calc('2*(3+4)-5')==9","eval("),
 ("HC5","EN","`def coin_change(coins, amount):` minimum number of coins to make amount, or -1 if impossible. Code only.",
  "assert coin_change([1,2,5],11)==3\nassert coin_change([2],3)==-1\nassert coin_change([1],0)==0",None),
 ("HC6","EN","`def max_sliding_window(nums, k):` return list of the max of each contiguous window of size k (aim for O(n)). Code only.",
  "assert max_sliding_window([1,3,-1,-3,5,3,6,7],3)==[3,3,5,5,6,7]\nassert max_sliding_window([1],1)==[1]",None),
 ("HC7","JP","`def word_break(s, words):` s を words のリストの単語に分割できるなら True。コードのみ。",
  "assert word_break('leetcode',['leet','code'])==True\nassert word_break('applepenapple',['apple','pen'])==True\nassert word_break('catsand',['cats','dog'])==False",None),
 ("HC8","CN","实现 `def spiral_order(matrix):` 按顺时针螺旋顺序返回矩阵所有元素的列表。只给代码。",
  "assert spiral_order([[1,2,3],[4,5,6],[7,8,9]])==[1,2,3,6,9,8,7,4,5]\nassert spiral_order([[1,2],[3,4]])==[1,2,4,3]",None),
]

# ---------- 多步推理/数学（提取 ANSWER 自动判）id, lang, prompt, kind, expected ----------
HR = [
 ("HR1","CN","一个水池，甲管单独注满需 6 小时，乙管单独需 4 小时。先单开甲管 2 小时，之后两管同时开，还需多少小时才能注满？请一步步推理，最后一行只写 'ANSWER: 数字(小时)'。","num",1.6),
 ("HR2","EN","A bat and a ball cost $1.10 together. The bat costs $1.00 more than the ball. How many CENTS does the ball cost? Reason step by step, last line only 'ANSWER: <number>'.","num",5),
 ("HR3","EN","How many distinct arrangements are there of the letters in the word 'BANANA'? Reason, then last line 'ANSWER: <number>'.","num",60),
 ("HR4","CN","今年父亲的年龄是儿子的 4 倍，5 年后父亲的年龄是儿子的 3 倍。儿子今年几岁？一步步推理，最后一行 'ANSWER: 数字'。","num",10),
 ("HR5","JP","ある商品を定価の2割引で売ると、利益が原価の2割になる。定価は原価の何倍か。順を追って考え、最後の行に 'ANSWER: 数字' のみ。","num",1.5),
 ("HR6","EN","In a race: A finished before B. C finished after B. D finished before A. Who finished LAST? Last line 'ANSWER: <letter>'.","str","C"),
]

# ---------- 更广知识（关键词任一命中）id, lang, prompt, keywords ----------
K = [
 ("K1","EN","In the OSI 7-layer model, what is the layer NUMBER of the Transport layer? Answer briefly.",["4","four","第四"]),
 ("K2","CN","TCP 三次握手中，第二次握手(服务器->客户端)的报文段同时置位了哪两个标志位？",["SYN","ACK"]),
 ("K3","JP","東京都内にある世界一高い自立式電波塔の名称は？",["スカイツリー","skytree","晴空塔"]),
 ("K4","EN","What is the worst-case time complexity of heapsort, in big-O notation?",["n log n","nlogn","n*log","nlog n"]),
 ("K5","CN","Python 的 GIL 三个字母是哪三个英文单词的缩写？",["global interpreter lock","全局解释器锁"]),
 ("K6","JP","ストレージの RAID 1 を一言で言うと、どんな仕組み？",["ミラー","mirror","镜像","冗長"]),
]

# ---------- 多约束指令（自定义校验）----------
def chk_if1(t):
    body = re.sub(r"```.*?```", "", t, flags=re.S).strip()
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    if len(sents) != 3: return False
    if "," in body: return False
    for s in sents:
        words = s.rstrip(".!?").split()
        if len(words) > 8: return False
        if "data" not in s.lower(): return False
    return True
def chk_if2(t):
    m = re.search(r"\{.*\}", t, re.S)
    try:
        o = json.loads(m.group(0))
    except Exception:
        return False
    return ("李雷" in str(o.get("name","")) and str(o.get("age"))=="28" and "大阪" in str(o.get("city","")))
def chk_if3(t):
    nums = re.findall(r"\d+", t)
    got = [int(x) for x in nums][:5]
    return got == [2,3,5,7,11]
def chk_if4(t):
    return "mhtirogla" in t.replace(" ","").lower()
IF = [
 ("IF1","EN","Write exactly three sentences. Each sentence must be 8 words or fewer. Every sentence must contain the word 'data'. Do not use any commas anywhere. Output only the sentences, nothing else.", chk_if1),
 ("IF2","CN","从下面这句话提取信息，只输出一个 JSON 对象，字段为 name、age(数字)、city：『李雷今年28岁，住在大阪。』", chk_if2),
 ("IF3","EN","Output the first 5 prime numbers as a comma-separated list on a single line. Nothing else.", chk_if3),
 ("IF4","EN","Reverse the string 'algorithm' and output ONLY the reversed string.", chk_if4),
]

# ---------- 更难工具 ----------
TT = [  # id, lang, prompt, expect_tool, required, expect_none
 ("TT1","EN","Find the current weather in Paris, then email a one-line summary to ann@x.com.","get_weather",["city"],False),
 ("TT2","CN","给张三发封邮件，说会议改到下午三点。",None,None,True),   # 缺收件人邮箱→应追问，不该编 send_email
 ("TT3","CN","帮我记一下：我家 WiFi 密码是 abc123。",None,None,True),  # 无记忆工具→应直接应答、不调任何工具
 ("TT4","EN","I need to know what 2 to the power of 20 equals.","calculator",["expression"],False),
]

# ---------- 广度(盲评)----------
BR = [
 ("BR1","CN","用一句话(不超过40字)忠实概括下面这段话，不得添加原文没有的信息：『田町站位于东京港区，是JR山手线和京浜东北线的车站。车站附近写字楼林立，午餐时间餐厅人很多。近年来周边在进行大规模再开发。』"),
 ("BR2","EN","Translate into natural Japanese (keep the nuance/politeness): 'Could you possibly let me know by tomorrow whether the meeting room is available?'"),
]

def extract_answer(text):
    m = re.findall(r"ANSWER\s*[:：]\s*([^\n]+)", text, re.I)
    return (m[-1].strip() if m else text.strip().splitlines()[-1] if text.strip() else "")

def num_eq(got, want, tol=0.02):
    m = re.search(r"-?\d+\.?\d*", got.replace(",", ""))
    if not m: return False
    try: return abs(float(m.group()) - want) <= tol
    except Exception: return False

def run_hc(model, prompt, test, forbid):
    # 注意：本 harness 不调用 eval()。forbid="eval(" 仅作"检测字符串"，
    # 用于判定模型生成的代码是否偷用 eval(HC4 要求自己解析、禁用 eval)。
    # 模型代码经 run_code 在隔离子进程+15s 超时内执行。
    p = 0; samples = []; parts = []
    for seed in range(1, REPEAT + 1):
        r = chat(model, prompt, seed=seed, max_tokens=2000)
        if "error" in r: samples.append({"err": r["error"]}); continue
        code = extract_code(r["content"])
        # 违反禁用约束不再直接 continue：那样连「实现对不对」都测不到，一律 0 分。
        # 改成 F2P=各条断言（实现对了多少）、P2P=有没有违规用禁用构造，两件事分开记。
        v = run_code_verdict(code, test)
        if forbid:
            used = forbid in code
            v.p2p_add(not used)
            if used:
                v.note(f"用了禁用的 {forbid}")
        p += 1 if v.passed else 0
        parts.append(v.partial)
        samples.append({"ok": v.passed, "info": v.detail, **v.as_dict(), "tps": r.get("tps"),
                         "finish_reason": r.get("finish_reason"), "reasoning_len": r.get("reasoning_len")})
    return p, REPEAT, samples, parts


def _infos(samples, n=2):
    """把前几次的判分说明拼成一行，方便扫日志看它是怎么错的。"""
    bits = [str(s.get("info") or s.get("err") or s.get("grader_error") or "") for s in samples]
    bits = [b for b in bits if b]
    return " ; ".join(bits[:n])

def main():
    out = {}; judge = []
    for model in MODELS:
        print(f"\n########## {model} ##########", flush=True)
        out[model] = {}
        for cid, lang, prompt, test, forbid in HC + HARD:
            p, n, s, parts = run_hc(model, prompt, test, forbid)
            pm = round(sum(parts) / len(parts), 4) if parts else 0.0
            # ★ 2026-09-06：HC（基础算法）与 X（高难算法）分成两个维度。
            #   实测 HC 已经彻底饱和（96%~100%），而 X 的跨度是 8%~78% ——
            #   混在一个维度里，HC 的满分会把 X 的区分度稀释掉一多半。
            #   HC 归回归卷（只用来发现退步），X 留在主卷当区分器。
            dim = "hardcode_x" if cid.startswith("X") else "hardcode"
            out[model][cid] = {"dim": dim, "lang": lang, "pass": p, "n": n,
                               "samples": s, "partial_mean": pm}
            print(f"  [{cid}/{lang}] {dim} {p}/{n} partial={pm}", flush=True)
        def _grade_reason(r, kind=None, exp=None):
            ans = extract_answer(r.get("content", ""))
            ok = num_eq(ans, exp) if kind == "num" else (str(exp).lower() in ans.lower())
            return ok, f"ans={ans[:30]!r}"
        for cid, lang, prompt, kind, exp in HR:
            p, n, s = repeat_chat(model, prompt,
                                  lambda r, kind=kind, exp=exp: _grade_reason(r, kind, exp),
                                  max_tokens=1200)
            out[model][cid] = {"dim": "reason", "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] reason {p}/{n} (exp={exp}) {_infos(s)}", flush=True)
        for cid, lang, prompt, kws in K:
            p, n, s = repeat_chat(model, prompt,
                                  lambda r, kws=kws: (contains_kw(r.get("content"), kws), ""),
                                  max_tokens=400)
            out[model][cid] = {"dim": "knowledge", "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] knowledge {p}/{n}", flush=True)
        for cid, lang, prompt, chk in IF:
            p, n, s = repeat_chat(model, prompt,
                                  lambda r, chk=chk: (bool(chk(r.get("content") or "")), ""),
                                  max_tokens=400)
            out[model][cid] = {"dim": "instruct", "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] instruct {p}/{n}", flush=True)
        for cid, lang, prompt, et, ra, en in TT:
            p, n, s = repeat_chat(model, prompt,
                                  lambda r, et=et, ra=ra, en=en: grade_tool(r, et, ra, en),
                                  tools=TOOLS, max_tokens=500)
            out[model][cid] = {"dim": "tool", "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] tool {p}/{n} | {_infos(s)}", flush=True)
        # 约束冲突：注意 IFC4 是**无冲突对照组**，误报也算错 —— 没有它的话，
        # 模型只要见到长约束列表就喊「有冲突」即可满分。
        for cid, lang, prompt, grade, mt in CONFLICT:
            p, n, s = repeat_chat(model, prompt, grade, max_tokens=mt)
            out[model][cid] = {"dim": "conflict", "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] conflict {p}/{n} | {_infos(s)}", flush=True)
        # 长上下文推理：接替已退役的 NIAH。整卷共用同一篇台账长文 ——
        # 文档放在 prompt 最前且逐题不变，前缀缓存命中后一个模型只 prefill 一次
        # （首问约 2~5 分钟，之后每问 1~2 秒；别为了省事把问题塞到文档前面，那样缓存全废）。
        doc = build_long_doc()
        first_lr = True
        for cid, lang, q, grade, mt in LONG_CASES:
            pp, ss = 0, []
            for i in range(REPEAT):
                try:
                    r = ask_long(model, doc, q, max_tokens=mt, seed=SEED_BASE + i + 1)
                except Exception as e:
                    ss.append({"err": str(e)[:200]}); continue
                ok, info = grade(r["ans"])
                pp += 1 if ok else 0
                ss.append({"ok": bool(ok), "info": info, "content": r["ans"][:300],
                           "finish_reason": r.get("finish_reason"),
                           "prompt_total": r.get("prompt_total")})
                if first_lr:
                    print(f"  (长文实际 {r.get('prompt_total')} tok，目标 {TARGET_TOKENS})", flush=True)
                    first_lr = False
            out[model][cid] = {"dim": "longctx", "lang": lang, "pass": pp, "n": REPEAT, "samples": ss}
            print(f"  [{cid}/{lang}] longctx {pp}/{REPEAT} | {_infos(ss)}", flush=True)
        # 多轮一致性：唯一走 repeat_turns 的一组（grade 收的是整轮对话的响应列表）。
        # max_tokens 给得比单轮题宽：四轮累计下来，最后一轮的上文已经不短了。
        for cid, lang, turns, grade, mt, dim in MULTI:
            p, n, s = repeat_turns(model, turns, grade, max_tokens=mt)
            out[model][cid] = {"dim": dim, "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] {dim} {p}/{n} | {_infos(s)}", flush=True)
        for cid, lang, prompt in BR:
            r = chat(model, prompt, seed=1, max_tokens=400)
            out[model][cid] = {"dim": "breadth", "lang": lang, "pass": None, "content": r.get("content","")}
            judge.append({"id": cid, "dim": "breadth", "lang": lang, "model": model,
                          "prompt": prompt, "answer": r.get("content","")})
            print(f"  [{cid}/{lang}] breadth -> 收集待评", flush=True)
        json.dump(out, open(RESULTS, "w"), ensure_ascii=False, indent=1)
        json.dump(judge, open(JUDGE, "w"), ensure_ascii=False, indent=1)
    print("\n=== 难卷全部完成 ===", flush=True)

if __name__ == "__main__":
    main()
