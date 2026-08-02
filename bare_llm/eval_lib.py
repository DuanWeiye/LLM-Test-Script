# A/B 评测公共库：发请求 + 各类自动判分器。被 smoke / full 脚本复用。
import json, subprocess, time, urllib.request, re, os, sys

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:12345/v1").rstrip("/") + "/chat/completions"
SCRATCH = os.path.dirname(os.path.abspath(__file__))

# 思考模型的 reasoning 也占 max_tokens 预算，用同一套给非思考模型定的紧预算(120-2000)测思考模型
# 必然大量假性截断——不是模型不行，是没给思考的空间（不公平，换哪个模型开思考都会这样被卡死）。
# 用环境变量兜底放宽，不改各用例原有的 max_tokens 语义（非思考模型跑照旧不受影响，MULT/MIN 默认不生效）。
_MT_MULT = float(os.environ.get("EVAL_MAX_TOKENS_MULT", "1"))
_MT_MIN = int(os.environ.get("EVAL_MAX_TOKENS_MIN", "0"))

# 采样参数覆盖：各用例默认走温度 0（贪心）做受控对照——确定性、跨模型跨时间可比，单次即可下结论。
# 代价是偏离各模型官方推荐设定：不少模型 generation_config 里明确 do_sample=true，贪心属于「没按说明书用」，
# 对经 RL 对齐的模型（尤其推理/agentic 模型）可能系统性低估，低温下也更容易触发重复退化。
# 这里允许用环境变量整体覆盖采样参数，用于跑「官方推荐设定」那一轮；不设则完全维持原有行为。
# ⚠️ 温度 >0 时单次结果带采样方差，据此出的分必须多次取均值才可下结论，不能和温度 0 的单次分直接比。
_TEMP = os.environ.get("EVAL_TEMPERATURE")
_TOP_P = os.environ.get("EVAL_TOP_P")
_TOP_K = os.environ.get("EVAL_TOP_K")

# 云端 OpenAI 兼容端点(DeepSeek 等)要 Bearer 鉴权；本地 llama-swap 不要，不设即不发该头(行为同旧版)。
_API_KEY = os.environ.get("LLM_API_KEY", "")
# 厂商专有请求字段(如 DeepSeek 关思考的 thinking:{type:disabled})，JSON 对象字符串，整体并进请求体。
# 收在这一层而不是散进各用例：关思考/调档的字段名各厂商都不同，用例不该知道后端是谁。
_EXTRA_BODY = json.loads(os.environ.get("LLM_EXTRA_BODY", "{}"))

def post(body, timeout=300):
    """统一出口：并入厂商专有字段 + 鉴权头后发请求。常规卷/难卷/NIAH 共用，避免各写一份。"""
    body = {**body, **_EXTRA_BODY}
    headers = {"Content-Type": "application/json"}
    if _API_KEY:
        headers["Authorization"] = "Bearer " + _API_KEY
    req = urllib.request.Request(BASE, json.dumps(body).encode(), headers)
    return json.load(urllib.request.urlopen(req, timeout=timeout))

# 有的思考模型服务端明确不接受采样参数（DeepSeek 思考模式文档：不支持 temperature/top_p/
# presence_penalty/frequency_penalty）。置 1 则一个采样参数都不发，由服务端自己定。
# ⚠️ 此时「温度 0」这个前提不成立，结果天然带采样方差，不能和温度 0 的单次分直接比。
_OMIT_SAMPLING = os.environ.get("EVAL_OMIT_SAMPLING") == "1"

def apply_sampling(body, temperature):
    """落定请求体的采样参数：默认用调用方给的温度，环境变量存在则整体覆盖。"""
    if _OMIT_SAMPLING:
        return body
    body["temperature"] = float(_TEMP) if _TEMP is not None else temperature
    if _TOP_P is not None:
        body["top_p"] = float(_TOP_P)
    if _TOP_K is not None:
        body["top_k"] = int(_TOP_K)
    return body

def chat(model, user, system="You are a helpful assistant.", temperature=0.0,
         seed=0, tools=None, max_tokens=1024):
    max_tokens = max(int(max_tokens * _MT_MULT), _MT_MIN, max_tokens)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    body = apply_sampling({"model": model, "messages": msgs,
                           "max_tokens": max_tokens, "stream": False}, temperature)
    if seed:
        body["seed"] = seed
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    t0 = time.time()
    try:
        d = post(body)
    except Exception as e:
        return {"error": str(e), "elapsed": round(time.time() - t0, 1)}
    elapsed = time.time() - t0
    msg = d["choices"][0]["message"]
    usage = d.get("usage") or {}
    # tps：本地 llama.cpp 给纯生成阶段的 timings.predicted_per_second；云端 API 没有这个字段，
    # 退化成 completion_tokens/墙钟(含排队与网络往返)——两者口径不同，跨本地/云端不可直接比速度。
    tps = (d.get("timings") or {}).get("predicted_per_second")
    if not tps and elapsed > 0:
        tps = (usage.get("completion_tokens") or 0) / elapsed
    return {"content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls"),
            "elapsed": round(elapsed, 1),
            "tps": round(tps or 0, 1),
            # 诊断字段（不参与判分）：思考模型可能把 max_tokens 吃在 reasoning 上被截断
            "finish_reason": d["choices"][0].get("finish_reason"),
            "reasoning_len": len(msg.get("reasoning_content") or ""),
            # 云端按 token 计费，留存 usage 以便事后核算成本；本地端点没有则为 {}
            "usage": usage}

def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S)
    return m[0].strip() if m else text.strip()

def run_code(code, test):
    """把模型代码 + 测试拼到一起跑，退出码 0 = 通过。隔离子进程、15s 超时。"""
    f = os.path.join(SCRATCH, "_sol.py")
    with open(f, "w") as fh:
        fh.write(code + "\n\n# ---- test ----\n" + test + "\nprint('ALL_PASS')\n")
    try:
        r = subprocess.run([sys.executable, f], capture_output=True, timeout=15, text=True)
        ok = (r.returncode == 0 and "ALL_PASS" in r.stdout)
        return ok, (r.stderr or r.stdout)[-300:].strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)

def _instrument_test(test_src):
    """把 test 里的**顶层 assert 逐条**包成 try/except 并各记一次结果，返回 (改写后源码, assert 条数)。

    用 AST 定位而不是按行切：A3(LRUCache) 有 setup 语句、A9(retry) 有跨行的装饰器函数定义，
    按行拆会把它们拆坏。非 assert 的语句原样保留 —— 它们跑挂说明模型代码根本用不起来，
    属于 P2P（可用性）层面的问题，而不是某一条断言答错。
    """
    import ast
    tree = ast.parse(test_src)
    parts, n = [], 0
    for node in tree.body:
        seg = ast.get_source_segment(test_src, node)
        if seg is None:
            continue
        # get_source_segment 对 FunctionDef/ClassDef **不含装饰器行**（其 lineno 指向 def/class 那行），
        # 直接用会把 A9 的 @retry(3) 丢掉、函数退化成未装饰版 —— 这是 oracle 自检抓到的真实 bug。
        # 不能改成整行切片：A3 的 `c.put(1,1); c.put(2,2)` 是同行两条语句，按行取会重复执行。
        # 故保留列精度，单独把装饰器源码补回去。
        decos = getattr(node, "decorator_list", None)
        if decos:
            _lines = test_src.splitlines()
            _dstart = min(d.lineno for d in decos)
            seg = "\n".join(_lines[_dstart - 1:node.lineno - 1]) + "\n" + seg
        # 顶层的 try/except 块整体也算一个检查项：这类结构就是「应当抛某异常」的断言写法
        # （try: f(); raise AssertionError(...) except X: pass）。不这样处理的话，块内 assert
        # 失败会抛出未捕获异常、整个脚本崩掉，连前面已经通过的断言也一并归零 —— 低估模型。
        if isinstance(node, (ast.Assert, ast.Try)):
            n += 1
            body = "\n".join("    " + ln for ln in seg.splitlines())
            parts.append("try:\n" + body + "\n    _R.append(True)\nexcept Exception:\n    _R.append(False)")
        else:
            parts.append(seg)
    return "\n".join(parts), n


def run_code_verdict(code, test, timeout=15):
    """跑模型代码 + 测试，返回 Verdict（逐条 assert 计分）。

    相比 run_code() 的「全过才算过」，这里把判分拆成：
      F2P = 各条 assert（答对几条就是几分）—— 「实现对了多少」
      P2P = 代码是否可用（能 exec、setup 不炸、不超时）—— 「产出物本身立不立得住」
    于是「写出能跑但边界条件错」和「写出根本跑不起来的东西」不再都是 0 分，
    在多数模型都接近满分的饱和区里仍能拉开差距。
    """
    from verdict import Verdict
    v = Verdict()
    try:
        instrumented, n_assert = _instrument_test(test)
    except SyntaxError as e:            # 题目自身的 test 写错了，属于框架问题而非模型答错
        v.grader_error = f"test 源码无法解析: {e}"
        return v
    if n_assert == 0:
        v.grader_error = "test 里没有顶层 assert，无法逐条计分"
        return v

    runner = (code + "\n\n# ---- test ----\n_R = []\n" + instrumented
              + "\nimport json as _json\nprint('__R__' + _json.dumps(_R))\n")
    f = os.path.join(SCRATCH, "_sol_verdict.py")
    with open(f, "w") as fh:
        fh.write(runner)
    try:
        r = subprocess.run([sys.executable, f], capture_output=True, timeout=timeout, text=True)
    except subprocess.TimeoutExpired:
        v.f2p_total = n_assert                      # 一条都没过
        return v.p2p_add(False).note("TIMEOUT")
    except Exception as e:
        v.grader_error = f"子进程异常: {e}"
        return v

    m = re.search(r"__R__(\[.*?\])", r.stdout or "")
    if not m:
        # 没拿到结果 = 代码/setup 阶段就崩了（语法错、未定义目标函数、装饰器不存在…）
        v.f2p_total = n_assert
        return v.p2p_add(False).note("代码不可用: " + (r.stderr or r.stdout or "")[-160:].strip())
    results = json.loads(m.group(1))
    v.f2p_passed, v.f2p_total = sum(1 for x in results if x), n_assert
    v.p2p_add(True)                                  # 跑起来了
    return v.note(f"assert {v.f2p_passed}/{n_assert}")


def grade_tool(resp, expect_tool, required_args=None, expect_none=False):
    """工具调用判分：选对工具 / 参数合规 / 该不该调。返回 (pass, 说明)。"""
    tcs = resp.get("tool_calls")
    if expect_none:
        return (not tcs), ("克制✓未调工具" if not tcs else f"误调了 {[t['function']['name'] for t in tcs]}")
    if not tcs:
        return False, "应调工具却没调"
    fn = tcs[0]["function"]
    name = fn["name"]
    if name != expect_tool:
        return False, f"选错工具: {name} (期望 {expect_tool})"
    try:
        args = json.loads(fn["arguments"])
    except Exception:
        return False, f"参数非合法JSON: {fn['arguments'][:80]}"
    for a in (required_args or []):
        if a not in args or args[a] in (None, ""):
            return False, f"缺必填参数 {a}; 实得 {list(args)}"
    return True, f"✓ {name}({args})"

# 工具调用测试用的工具集（OpenAI 格式）
TOOLS = [
    {"type": "function", "function": {
        "name": "get_weather", "description": "查询指定城市的当前天气",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名"}}, "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "calculator", "description": "计算一个数学表达式并返回结果",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "如 12*456"}}, "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "search_web", "description": "用关键词搜索互联网获取实时信息",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "send_email", "description": "发送一封邮件",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "description": "收件人邮箱"},
            "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"]}}},
]
