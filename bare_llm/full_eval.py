# 全量 A/B 评测：qwen3.6-35b-a3b vs qwen3-coder-next。
# 按模型分批(各只加载一次，避免 llama-swap 热切)。客观项自动判分，主观项收集留给 Claude 盲评。
import sys, json, time, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_lib import chat, extract_code, run_code, grade_tool, TOOLS, SCRATCH

MODELS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["qwen3.6-35b-a3b", "qwen3-coder-next"]
TAG = sys.argv[2] if len(sys.argv) > 2 else ""
RESULTS = f"{SCRATCH}/ab_results{TAG}.json"
JUDGE = f"{SCRATCH}/ab_judge_queue{TAG}.json"

# ---------- 编码用例（执行判分；3 次尝试取通过数）----------
CODE = [
 ("A1","EN","`def two_sum(nums, target):` 返回两元素相加==target 的下标 [i,j](i<j)。只给代码。",
  "assert sorted(two_sum([2,7,11,15],9))==[0,1]\nassert sorted(two_sum([3,2,4],6))==[1,2]"),
 ("A2","EN","`def is_balanced(s):` 判断 ()[]{} 是否配对平衡，返回 bool。只给代码。",
  "assert is_balanced('([]{})')==True\nassert is_balanced('([)]')==False\nassert is_balanced('')==True"),
 ("A3","CN","实现 `class LRUCache:`，`__init__(self,capacity)`、`get(self,key)`(不存在返回 -1)、`put(self,key,value)`，容量满淘汰最久未用。只给代码。",
  "c=LRUCache(2)\nc.put(1,1); c.put(2,2)\nassert c.get(1)==1\nc.put(3,3)\nassert c.get(2)==-1\nassert c.get(3)==3"),
 ("A4","JP","昇順配列で値 x が最初に現れる添字を返す `def first_index(arr, x):` を実装。無ければ -1。コードのみ。",
  "assert first_index([1,2,2,2,3],2)==1\nassert first_index([1,3,5],4)==-1\nassert first_index([],1)==-1"),
 ("A5","CN","下面的快排有 bug(会丢掉与 pivot 相等的重复元素)，请修正并返回 `def quicksort(a):`。只给修正后代码。\n```python\ndef quicksort(a):\n    if len(a)<=1: return a\n    p=a[0]\n    left=[x for x in a if x<p]\n    right=[x for x in a if x>p]\n    return quicksort(left)+[p]+quicksort(right)\n```",
  "assert quicksort([3,1,2,3,3,1])==[1,1,2,3,3,3]\nassert quicksort([])==[]"),
 ("A6","EN","`def merge_intervals(intervals):` 合并重叠区间，返回排序后的区间列表。只给代码。",
  "assert merge_intervals([[1,3],[2,6],[8,10]])==[[1,6],[8,10]]\nassert merge_intervals([[1,4],[4,5]])==[[1,5]]"),
 ("A7","CN","下面函数想求 1+2+...+n 但有 off-by-one bug，请修正并返回 `def sum_to_n(n):`。只给代码。\n```python\ndef sum_to_n(n):\n    t=0\n    for i in range(n): t+=i\n    return t\n```",
  "assert sum_to_n(5)==15\nassert sum_to_n(1)==1\nassert sum_to_n(100)==5050"),
 ("A8","EN","`def parse_csv(text):` parse CSV text; SKIP any row that does not have exactly 3 comma-separated fields; return a list of 3-tuples (strings, stripped). Code only.",
  "d='a,b,c\\nx,y\\n1, 2 , 3\\nbad\\np,q,r'\nassert parse_csv(d)==[('a','b','c'),('1','2','3'),('p','q','r')]"),
 ("A9","EN","Implement a decorator `def retry(times):` that retries the wrapped function up to `times` total attempts if it raises, returning its result; if all attempts raise, re-raise the last exception. Code only.",
  "import itertools\nc=itertools.count()\n@retry(3)\ndef f():\n    n=next(c)\n    if n<2: raise ValueError('x')\n    return 'ok'\nassert f()=='ok'"),
 ("A10","EN","`def group_anagrams(words):` group words that are anagrams; return a list of groups (any order). Code only.",
  "r=group_anagrams(['eat','tea','tan','ate','nat','bat'])\nkey=sorted(sorted(g) for g in r)\nassert key==sorted([sorted(x) for x in [['eat','tea','ate'],['tan','nat'],['bat']]])"),
 ("A11","CN","`def is_valid_ipv4(s):` 判断是否合法 IPv4(四段 0-255、无前导零如 01 视为非法、无多余字符)，返回 bool。只给代码。",
  "assert is_valid_ipv4('192.168.1.1')==True\nassert is_valid_ipv4('256.1.1.1')==False\nassert is_valid_ipv4('1.2.3')==False\nassert is_valid_ipv4('01.2.3.4')==False"),
 ("A12","JP","ランレングス圧縮 `def rle_encode(s):` を実装。'aaabbc'→'a3b2c1'。コードのみ。",
  "assert rle_encode('aaabbc')=='a3b2c1'\nassert rle_encode('')==''\nassert rle_encode('x')=='x1'"),
]

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

def run_code_case(model, prompt, test):
    seeds=[(0.0,0),(0.7,2),(0.7,3)]
    passes=0; samples=[]
    for temp,seed in seeds:
        r=chat(model,prompt,temperature=temp,seed=seed,max_tokens=1500)
        if "error" in r: samples.append({"err":r["error"]}); continue
        ok,info=run_code(extract_code(r["content"]),test)
        passes+=1 if ok else 0
        samples.append({"ok":ok,"info":info,"tps":r.get("tps")})
    return passes,len(seeds),samples

def main():
    out={}; judge=[]
    for model in MODELS:
        print(f"\n########## MODEL: {model} ##########",flush=True)
        out[model]={}
        # A 编码
        for cid,lang,prompt,test in CODE+TRI:
            p,n,s=run_code_case(model,prompt,test)
            out[model][cid]={"dim":"code","lang":lang,"pass":p,"n":n,"samples":s}
            print(f"  [{cid}/{lang}] code pass {p}/{n}",flush=True)
        # B 工具
        for cid,lang,prompt,et,ra,en in TOOL:
            r=chat(model,prompt,tools=TOOLS,temperature=0,max_tokens=512)
            if "error" in r:
                out[model][cid]={"dim":"tool","lang":lang,"pass":False,"info":r["error"]}; continue
            ok,info=grade_tool(r,et,ra,en)
            out[model][cid]={"dim":"tool","lang":lang,"pass":ok,"info":info,
                             "content":r["content"][:200],"tool_calls":r.get("tool_calls")}
            print(f"  [{cid}/{lang}] tool {'PASS' if ok else 'FAIL'} | {info}",flush=True)
        # C 事实/幻觉
        for cid,lang,prompt,mc in FACT:
            r=chat(model,prompt,temperature=0,max_tokens=800)
            content=r.get("content","")
            if mc is not None:  # 自动判
                ok=any(k.lower() in content.lower() for k in mc)
                out[model][cid]={"dim":"fact","lang":lang,"pass":ok,"content":content[:300]}
                print(f"  [{cid}/{lang}] fact {'PASS' if ok else 'FAIL'}",flush=True)
            else:  # 留给盲评
                out[model][cid]={"dim":"halluc","lang":lang,"pass":None,"content":content}
                judge.append({"id":cid,"dim":"halluc","lang":lang,"model":model,"prompt":prompt,"answer":content})
                print(f"  [{cid}/{lang}] halluc -> 收集待评({len(content)}字)",flush=True)
        # D 格式
        for cid,lang,prompt,chk in FORMAT:
            r=chat(model,prompt,temperature=0,max_tokens=400)
            content=r.get("content","")
            try: ok=bool(chk(content))
            except Exception: ok=False
            out[model][cid]={"dim":"format","lang":lang,"pass":ok,"content":content[:200]}
            print(f"  [{cid}/{lang}] format {'PASS' if ok else 'FAIL'}",flush=True)
        # 代码质量盲评素材：取 A3/A9 的产物留给 Claude 评质量
        for cid in ["A3","A9","A5"]:
            r=chat(model,dict((c[0],c[2]) for c in CODE)[cid],temperature=0,max_tokens=1500)
            judge.append({"id":f"Q-{cid}","dim":"code_quality","lang":"-","model":model,
                          "prompt":dict((c[0],c[2]) for c in CODE)[cid],"answer":r.get("content","")})
        json.dump(out,open(RESULTS,"w"),ensure_ascii=False,indent=1)
        json.dump(judge,open(JUDGE,"w"),ensure_ascii=False,indent=1)
    print("\n=== 全部完成，结果已存盘 ===",flush=True)
    print("RESULTS:",RESULTS); print("JUDGE_QUEUE:",JUDGE)

if __name__=="__main__":
    main()
