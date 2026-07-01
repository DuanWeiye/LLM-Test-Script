# A/B 评测公共库：发请求 + 各类自动判分器。被 smoke / full 脚本复用。
import json, subprocess, time, urllib.request, re, os, sys

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:12345/v1").rstrip("/") + "/chat/completions"
SCRATCH = os.path.dirname(os.path.abspath(__file__))

# 思考模型的 reasoning 也占 max_tokens 预算，用同一套给非思考模型定的紧预算(120-2000)测思考模型
# 必然大量假性截断——不是模型不行，是没给思考的空间（不公平，换哪个模型开思考都会这样被卡死）。
# 用环境变量兜底放宽，不改各用例原有的 max_tokens 语义（非思考模型跑照旧不受影响，MULT/MIN 默认不生效）。
_MT_MULT = float(os.environ.get("EVAL_MAX_TOKENS_MULT", "1"))
_MT_MIN = int(os.environ.get("EVAL_MAX_TOKENS_MIN", "0"))

def chat(model, user, system="You are a helpful assistant.", temperature=0.0,
         seed=0, tools=None, max_tokens=1024):
    max_tokens = max(int(max_tokens * _MT_MULT), _MT_MIN, max_tokens)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    body = {"model": model, "messages": msgs, "temperature": temperature,
            "max_tokens": max_tokens, "stream": False}
    if seed:
        body["seed"] = seed
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(BASE, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=300))
    except Exception as e:
        return {"error": str(e), "elapsed": round(time.time() - t0, 1)}
    msg = d["choices"][0]["message"]
    return {"content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls"),
            "elapsed": round(time.time() - t0, 1),
            "tps": round(d.get("timings", {}).get("predicted_per_second", 0), 1),
            # 诊断字段（不参与判分）：思考模型可能把 max_tokens 吃在 reasoning 上被截断
            "finish_reason": d["choices"][0].get("finish_reason"),
            "reasoning_len": len(msg.get("reasoning_content") or "")}

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
