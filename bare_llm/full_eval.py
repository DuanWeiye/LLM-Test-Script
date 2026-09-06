# 全量 A/B 评测：qwen3.6-35b-a3b vs qwen3-coder-next。
# 按模型分批(各只加载一次，避免 llama-swap 热切)。客观项自动判分，主观项收集留给 Claude 盲评。
import sys, json, time, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_lib import (chat, extract_code, run_code, run_code_verdict, grade_tool,
                      repeat_chat, contains_kw, REPEAT, TOOLS, SCRATCH)

MODELS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["qwen3.6-35b-a3b", "qwen3-coder-next"]
TAG = sys.argv[2] if len(sys.argv) > 2 else ""
RESULTS = f"{SCRATCH}/ab_results{TAG}.json"
JUDGE = f"{SCRATCH}/ab_judge_queue{TAG}.json"

# ---------- 编码用例（执行判分；3 次尝试取通过数）----------
# CODE 卷（12 道普通单函数题）已于 2026-08-02 删除：
# 地板模型 100% 通过，对区分模型没有价值。保留的高难题见 cases_hard.py。
CODE = []

# ---------- 工具调用用例 ----------
TOOL = [  # (id, lang, prompt, expect_tool, required_args, expect_none)
 ("B1","CN","东京现在天气怎么样？","get_weather",["city"],False),
 ("B2","CN","帮我算一下 12 乘以 456 等于多少。","calculator",["expression"],False),
 ("B3","CN","1+1 等于几？直接告诉我。",None,None,True),
 ("B4","JP","最新のAIニュースをネットで調べてください。","search_web",["query"],False),
 ("B5","EN","Write me a short poem about cats.",None,None,True),
 ("B6","EN","Send an email to boss@corp.com with subject 'Report' and body 'Done today.'","send_email",["to","subject","body"],False),
 ("B7","CN","帮我发一封邮件，提醒明天开会。",None,None,True),  # 缺收件人→应反问、不应编 send_email
 ("B8","EN","What is 15% of 8000?","calculator",["expression"],False),
 ("B9","CN","查一下『北京』今天的天气。","get_weather",["city"],False),
 ("B10","EN","Translate 'good morning' into French for me.",None,None,True),  # 无需工具
]

# ---------- 事实/幻觉用例 ----------
FACT = [  # (id, lang, prompt, must_contain or None→judge)
 ("C1","CN","东京的田町站(Tamachi)属于东京都的哪个区？只回答区名。",["港区","港"]),
 ("C2","EN","What does HTTP status code 418 mean? Answer briefly.",["teapot"]),
 ("C6","CN","科幻小说《三体》的作者是谁？",["刘慈欣"]),
 ("C7","CN","东京塔(Tokyo Tower)的高度大约是多少米？",["333"]),
 ("C3","JP","2027年のノーベル物理学賞の受賞者は誰ですか？",None),     # 未来→应拒答
 ("C4","CN","请解释 Python 标准库 asyncio 里的 `asyncio.gather_timeout()` 函数怎么用。",None),  # 假函数
 ("C5","CN","请举例说明 pandas 的 `DataFrame.rolling_apply_parallel()` 方法的用法。",None),       # 假方法
 ("C8","EN","Who won the 2026 FIFA World Cup final, and what was the score?",None),  # 今天2026-06-28, 多半未结束→应诚实说未知/未结束
]

# ---------- 格式/指令用例 ----------
def chk_json(t):
    m=re.search(r"\{.*\}",t,re.S)
    try:
        o=json.loads(m.group(0)); return ("name" in o and "age" in o)
    except Exception: return False
def chk_exact_ok(t): return t.strip()=="OK"
def chk_lines3(t):
    ls=[l for l in t.strip().splitlines() if l.strip()]
    return len(ls)==3 and all(l.lstrip().startswith("-") for l in ls)
def chk_ja_short(t):
    body=t.strip()
    has_ja=bool(re.search(r"[ぁ-んァ-ヶ一-龥]",body))
    return has_ja and len(body)<=40
def chk_onesentence(t):
    body=t.strip()
    return len(body)<=40 and body.count("。")<=1
def chk_mdtable(t):
    return t.count("|")>=6 and re.search(r"-{2,}",t) is not None
FORMAT = [  # (id, lang, prompt, checker)
 ("D1","CN",'只输出一个 JSON 对象(无多余文字)，字段 name="太郎"(字符串)、age=30(数字)。',chk_json),
 ("D2","JP","日本語で、20文字以内で自己紹介してください。",chk_ja_short),
 ("D3","CN","只列出恰好 3 个 Python 的 Web 框架，每行以 `- ` 开头，不要任何其它文字。",chk_lines3),
 ("D4","EN","Reply with exactly the word OK and nothing else.",chk_exact_ok),
 ("D5","CN","用不超过 20 个字、一句话概括什么是『闭包』。",chk_onesentence),
 ("D6","EN","Output a markdown table with columns Name and Age, and exactly 2 data rows. Table only.",chk_mdtable),
]

# ---------- 三语一致性 ----------
TRI = [  # (id, lang, prompt, test)  —— 同一编码任务三语
 ("E1-EN","EN","`def reverse_words(s):` reverse the order of words in a sentence. 'hello world'->'world hello'. Code only.",
  "assert reverse_words('hello world')=='world hello'\nassert reverse_words('a b c')=='c b a'"),
 ("E1-CN","CN","实现 `def reverse_words(s):` 反转句子中单词顺序，'hello world'->'world hello'。只给代码。",
  "assert reverse_words('hello world')=='world hello'\nassert reverse_words('a b c')=='c b a'"),
 ("E1-JP","JP","文中の単語の順序を逆にする `def reverse_words(s):` を実装。'hello world'->'world hello'。コードのみ。",
  "assert reverse_words('hello world')=='world hello'\nassert reverse_words('a b c')=='c b a'"),
]

def _infos(samples, n=2):
    """把前几次的判分说明拼成一行，方便扫日志看它是怎么错的。"""
    bits=[str(s.get("info") or s.get("err") or s.get("grader_error") or "") for s in samples]
    bits=[b for b in bits if b]
    return " ; ".join(bits[:n])


def run_code_case(model, prompt, test):
    """同一题按各模型推荐采样跑 REPEAT 次（seed 各不同）。

    除「几次全过」计数外，另记逐条 assert 的 partial（run_code_verdict）：
    F2P=各条断言、P2P=代码本身跑不跑得起来。这样「能跑但边界条件错」与「根本跑不起来」
    不再都记 0 分，在多数模型都接近满分的饱和区里仍能拉开差距。
    """
    passes=0; samples=[]; parts=[]
    for seed in range(1, REPEAT + 1):
        r=chat(model,prompt,seed=seed,max_tokens=1500)
        if "error" in r: samples.append({"err":r["error"]}); continue
        v=run_code_verdict(extract_code(r["content"]),test)
        passes+=1 if v.passed else 0
        parts.append(v.partial)
        samples.append({"ok":v.passed,"info":v.detail,**v.as_dict(),"tps":r.get("tps"),
                         "finish_reason":r.get("finish_reason"),"reasoning_len":r.get("reasoning_len")})
    return passes,REPEAT,samples,parts

def main():
    out={}; judge=[]
    for model in MODELS:
        print(f"\n########## MODEL: {model} ##########",flush=True)
        out[model]={}
        # A 编码
        for cid,lang,prompt,test in CODE+TRI:
            p,n,s,parts=run_code_case(model,prompt,test)
            pm=round(sum(parts)/len(parts),4) if parts else 0.0
            out[model][cid]={"dim":"code","lang":lang,"pass":p,"n":n,"samples":s,"partial_mean":pm}
            print(f"  [{cid}/{lang}] code pass {p}/{n} partial={pm}",flush=True)
        # B 工具（每题 k 次）
        for cid,lang,prompt,et,ra,en in TOOL:
            p,n,s=repeat_chat(model,prompt,
                              lambda r,et=et,ra=ra,en=en: grade_tool(r,et,ra,en),
                              tools=TOOLS,max_tokens=512)
            out[model][cid]={"dim":"tool","lang":lang,"pass":p,"n":n,"samples":s}
            print(f"  [{cid}/{lang}] tool {p}/{n} | {_infos(s)}",flush=True)
        # C 事实/幻觉
        for cid,lang,prompt,mc in FACT:
            if mc is not None:  # 自动判，跑 k 次
                p,n,s=repeat_chat(model,prompt,
                                  lambda r,mc=mc: (contains_kw(r.get("content"), mc),""),
                                  max_tokens=800)
                out[model][cid]={"dim":"fact","lang":lang,"pass":p,"n":n,"samples":s}
                print(f"  [{cid}/{lang}] fact {p}/{n}",flush=True)
            else:  # 留给盲评：不自动判分，跑一次收集产物即可
                r=chat(model,prompt,seed=1,max_tokens=800)
                content=r.get("content","")
                out[model][cid]={"dim":"halluc","lang":lang,"pass":None,"content":content}
                judge.append({"id":cid,"dim":"halluc","lang":lang,"model":model,"prompt":prompt,"answer":content})
                print(f"  [{cid}/{lang}] halluc -> 收集待评({len(content)}字)",flush=True)
        # D 格式（每题 k 次）
        for cid,lang,prompt,chk in FORMAT:
            p,n,s=repeat_chat(model,prompt,
                              lambda r,chk=chk: (bool(chk(r.get("content") or "")),""),
                              max_tokens=400)
            out[model][cid]={"dim":"format","lang":lang,"pass":p,"n":n,"samples":s}
            print(f"  [{cid}/{lang}] format {p}/{n}",flush=True)
        json.dump(out,open(RESULTS,"w"),ensure_ascii=False,indent=1)
        json.dump(judge,open(JUDGE,"w"),ensure_ascii=False,indent=1)
    print("\n=== 全部完成，结果已存盘 ===",flush=True)
    print("RESULTS:",RESULTS); print("JUDGE_QUEUE:",JUDGE)

if __name__=="__main__":
    main()
