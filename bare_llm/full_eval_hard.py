# 难卷 A/B：四模型，思考全程关(不传 enable_thinking=服务端默认关)。
# 专挑能拉开差距的题：硬算法/多步推理/更广知识/多约束指令/更难工具/广度。
import sys, json, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_lib import chat, extract_code, run_code, grade_tool, TOOLS, SCRATCH

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
    seeds = [(0.0, 0), (0.7, 2)]
    p = 0; samples = []
    for temp, seed in seeds:
        r = chat(model, prompt, temperature=temp, seed=seed, max_tokens=2000)
        if "error" in r: samples.append({"err": r["error"]}); continue
        code = extract_code(r["content"])
        if forbid and forbid in code:
            samples.append({"ok": False, "info": f"用了禁用的 {forbid}"}); continue
        ok, info = run_code(code, test)
        p += 1 if ok else 0
        samples.append({"ok": ok, "info": info, "tps": r.get("tps"),
                         "finish_reason": r.get("finish_reason"), "reasoning_len": r.get("reasoning_len")})
    return p, len(seeds), samples

def main():
    out = {}; judge = []
    for model in MODELS:
        print(f"\n########## {model} ##########", flush=True)
        out[model] = {}
        for cid, lang, prompt, test, forbid in HC:
            p, n, s = run_hc(model, prompt, test, forbid)
            out[model][cid] = {"dim": "hardcode", "lang": lang, "pass": p, "n": n, "samples": s}
            print(f"  [{cid}/{lang}] hardcode {p}/{n}", flush=True)
        for cid, lang, prompt, kind, exp in HR:
            r = chat(model, prompt, temperature=0, max_tokens=1200)
            ans = extract_answer(r.get("content", ""))
            ok = num_eq(ans, exp) if kind == "num" else (str(exp).lower() in ans.lower())
            out[model][cid] = {"dim": "reason", "lang": lang, "pass": ok, "answer": ans[:60], "content": r.get("content","")[-300:],
                               "finish_reason": r.get("finish_reason")}
            print(f"  [{cid}/{lang}] reason {'PASS' if ok else 'FAIL'} (ans={ans[:30]!r} exp={exp})", flush=True)
        for cid, lang, prompt, kws in K:
            r = chat(model, prompt, temperature=0, max_tokens=400)
            c = r.get("content", "")
            ok = any(k.lower() in c.lower() for k in kws)
            out[model][cid] = {"dim": "knowledge", "lang": lang, "pass": ok, "content": c[:200],
                               "finish_reason": r.get("finish_reason")}
            print(f"  [{cid}/{lang}] knowledge {'PASS' if ok else 'FAIL'}", flush=True)
        for cid, lang, prompt, chk in IF:
            r = chat(model, prompt, temperature=0, max_tokens=400)
            c = r.get("content", "")
            try: ok = bool(chk(c))
            except Exception: ok = False
            out[model][cid] = {"dim": "instruct", "lang": lang, "pass": ok, "content": c[:200],
                               "finish_reason": r.get("finish_reason")}
            print(f"  [{cid}/{lang}] instruct {'PASS' if ok else 'FAIL'}", flush=True)
        for cid, lang, prompt, et, ra, en in TT:
            r = chat(model, prompt, tools=TOOLS, temperature=0, max_tokens=500)
            if "error" in r: out[model][cid] = {"dim":"tool","lang":lang,"pass":False,"info":r["error"]}; continue
            ok, info = grade_tool(r, et, ra, en)
            out[model][cid] = {"dim": "tool", "lang": lang, "pass": ok, "info": info,
                               "content": r.get("content","")[:160], "tool_calls": r.get("tool_calls"),
                               "finish_reason": r.get("finish_reason")}
            print(f"  [{cid}/{lang}] tool {'PASS' if ok else 'FAIL'} | {info}", flush=True)
        for cid, lang, prompt in BR:
            r = chat(model, prompt, temperature=0, max_tokens=400)
            out[model][cid] = {"dim": "breadth", "lang": lang, "pass": None, "content": r.get("content","")}
            judge.append({"id": cid, "dim": "breadth", "lang": lang, "model": model,
                          "prompt": prompt, "answer": r.get("content","")})
            print(f"  [{cid}/{lang}] breadth -> 收集待评", flush=True)
        json.dump(out, open(RESULTS, "w"), ensure_ascii=False, indent=1)
        json.dump(judge, open(JUDGE, "w"), ensure_ascii=False, indent=1)
    print("\n=== 难卷全部完成 ===", flush=True)

if __name__ == "__main__":
    main()
