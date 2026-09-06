# A/B 评测公共库：发请求 + 各类自动判分器。被 smoke / full 脚本复用。
import atexit, json, shutil, subprocess, tempfile, time, urllib.request, re, os, sys

BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:12345/v1").rstrip("/") + "/chat/completions"
SCRATCH = os.path.dirname(os.path.abspath(__file__))

# 思考模型的 reasoning 也占 max_tokens 预算，用同一套给非思考模型定的紧预算(120-2000)测思考模型
# 必然大量假性截断——不是模型不行，是没给思考的空间（不公平，换哪个模型开思考都会这样被卡死）。
# 用环境变量兜底放宽，不改各用例原有的 max_tokens 语义（非思考模型跑照旧不受影响，MULT/MIN 默认不生效）。
_MT_MULT = float(os.environ.get("EVAL_MAX_TOKENS_MULT", "1"))
_MT_MIN = int(os.environ.get("EVAL_MAX_TOKENS_MIN", "0"))

# 采样参数：**默认一个都不发**，让端点按各模型自己的官方推荐设定跑（2026-08-02 主人定的方向）。
# 理由：温度 0（贪心）虽然确定性好、单次即可下结论，但它偏离各模型的 generation_config
# ——不少模型明确 do_sample=true，贪心属于「没按说明书用」，对经 RL 对齐的模型（尤其推理/agentic）
# 可能系统性低估，低温下还更容易触发重复退化，有些模型在温度 0 下甚至根本不能正常工作。
# 本机 llama-swap 已给每个模型按 generation_config 配好 --temp/--top-p/--top-k，
# 云端 API 不传即用官方默认，所以「不发」就等于「按各模型推荐值跑」，不必在评测脚本里维护温度表。
# ⚠️ 代价：结果带采样方差，所以每题要跑多次取均值（见 REPEAT / repeat_chat）。
# 想复现旧的温度 0 贪心对照，用 EVAL_TEMPERATURE=0 强制覆盖即可。
_TEMP = os.environ.get("EVAL_TEMPERATURE")
_TOP_P = os.environ.get("EVAL_TOP_P")
_TOP_K = os.environ.get("EVAL_TOP_K")

# 每道题重复几次。温度非 0 之后单次结果就是一次抽样，必须多次才能下结论。
REPEAT = int(os.environ.get("EVAL_REPEAT", "3"))

# seed 起点。默认 0 → seed 用 1..REPEAT。
# 想给同一个模型再跑一轮**独立**样本（例如判断某处差异是真信号还是采样噪声）时，
# 设 EVAL_SEED_BASE=3 就拿到 seed 4..6，与上一轮不重叠，两轮结果可直接合并成 2×REPEAT 次采样。
# 注意：本地 llama.cpp 认 seed 但并发 slot / 批处理下并非严格确定，相同 seed 重跑结果也会变；
# 换 seed 是为了让「独立性」在口径上站得住，不是因为相同 seed 一定复现。
SEED_BASE = int(os.environ.get("EVAL_SEED_BASE", "0"))

# 云端 OpenAI 兼容端点(DeepSeek 等)要 Bearer 鉴权；本地 llama-swap 不要，不设即不发该头(行为同旧版)。
_API_KEY = os.environ.get("LLM_API_KEY", "")
# 厂商专有请求字段(如 DeepSeek 关思考的 thinking:{type:disabled})，JSON 对象字符串，整体并进请求体。
# 收在这一层而不是散进各用例：关思考/调档的字段名各厂商都不同，用例不该知道后端是谁。
_EXTRA_BODY = json.loads(os.environ.get("LLM_EXTRA_BODY", "{}"))

# 单次请求的 HTTP 超时。思考模型给大 max_tokens 时一次能跑好几分钟
# （实测某思考模型 32000 tokens 用了 261 秒），默认 300 秒会把它全判成网络错误。
_HTTP_TIMEOUT = int(os.environ.get("EVAL_HTTP_TIMEOUT", "300"))


def post(body, timeout=None):
    """统一出口：并入厂商专有字段 + 鉴权头后发请求。常规卷/难卷/NIAH 共用，避免各写一份。"""
    timeout = timeout or _HTTP_TIMEOUT
    body = {**body, **_EXTRA_BODY}
    headers = {"Content-Type": "application/json"}
    if _API_KEY:
        headers["Authorization"] = "Bearer " + _API_KEY
    req = urllib.request.Request(BASE, json.dumps(body).encode(), headers)
    return json.load(urllib.request.urlopen(req, timeout=timeout))

# 强制一个采样参数都不发，即使设了 EVAL_TEMPERATURE。
# （有的思考模型服务端明确不接受采样参数，如 DeepSeek 思考模式不支持
#   temperature/top_p/presence_penalty/frequency_penalty。）
# 注意：不设这个变量时**默认也是不发**，本开关只用于压过 EVAL_TEMPERATURE 之类的显式覆盖。
_OMIT_SAMPLING = os.environ.get("EVAL_OMIT_SAMPLING") == "1"

def apply_sampling(body, temperature=None):
    """落定请求体的采样参数。

    默认什么都不发 —— 由端点按各模型自己的推荐设定决定。
    只有显式给了环境变量（或调用方明确传了 temperature）才发对应参数。
    """
    if _OMIT_SAMPLING:
        return body
    if _TEMP is not None:
        body["temperature"] = float(_TEMP)
    elif temperature is not None:
        body["temperature"] = float(temperature)
    if _TOP_P is not None:
        body["top_p"] = float(_TOP_P)
    if _TOP_K is not None:
        body["top_k"] = int(_TOP_K)
    return body

def _one_call(model, msgs, temperature=None, seed=0, tools=None, max_tokens=1024):
    """发一次请求并解析响应。单轮 chat 与多轮 chat_turns 共用这个核心，
    保证两者的采样口径、max_tokens 处理、诊断字段完全一致 ——
    分成两份实现迟早会漂，而口径不一致的两组数字是不能放进同一张表的。"""
    max_tokens = max(int(max_tokens * _MT_MULT), _MT_MIN, max_tokens)
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


def chat(model, user, system="You are a helpful assistant.", temperature=None,
         seed=0, tools=None, max_tokens=1024):
    """单轮：一条 system + 一条 user。行为与重构前完全一致。"""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return _one_call(model, msgs, temperature=temperature, seed=seed,
                     tools=tools, max_tokens=max_tokens)


def chat_turns(model, turns, system="You are a helpful assistant.", temperature=None,
               seed=0, tools=None, max_tokens=1024):
    """多轮对话：`turns` 是按顺序发出的 user 消息列表，返回每轮的响应列表。

    **为什么要有多轮**：现有裸卷 100% 是单轮题，而真实使用几乎全是长对话 ——
    「早先定下的约定，聊了几轮之后还守不守」「被无关内容干扰后，早期的事实还记不记得」
    「后面改了主意，模型跟不跟得上」这三件事单轮题一个都测不到，
    偏偏它们才是日常用起来最常翻车的地方。

    把模型自己的回复接回历史（只回传 `content`，**不回传 `reasoning_content`** ——
    思考模型的官方用法就是多轮不回传思考内容，回传反而会让它把上一轮的草稿当成事实）。

    任何一轮出错就停下并把错误记在该轮，后面的轮次不再发 —— 历史断了以后
    再发下去，测的就不是同一件事了。
    """
    msgs = [{"role": "system", "content": system}]
    out = []
    for user in turns:
        msgs.append({"role": "user", "content": user})
        r = _one_call(model, msgs, temperature=temperature, seed=seed,
                      tools=tools, max_tokens=max_tokens)
        out.append(r)
        if "error" in r:
            break
        msgs.append({"role": "assistant", "content": r.get("content") or ""})
    return out


def repeat_turns(model, turns, grade, k=None, **kw):
    """多轮题跑 k 次、逐次判分，返回 (通过次数, k, 样本列表)。

    与 repeat_chat 同构，区别是 `grade` 收到的是**整轮对话的响应列表**
    （fn(responses) -> (bool, str)），因为多轮题的判据往往要看最后一轮、
    也可能要看中间轮有没有提前崩。
    """
    k = k or REPEAT
    n_pass, samples = 0, []
    for i in range(k):
        rs = chat_turns(model, turns, seed=SEED_BASE + i + 1, **kw)
        err = next((r["error"] for r in rs if "error" in r), None)
        if err:
            samples.append({"err": err, "turns_done": len(rs)})
            continue
        try:
            ok, info = grade(rs)
        except Exception as e:                  # 判分器自己炸了，不该记成模型答错
            samples.append({"grader_error": str(e)[:200]})
            continue
        n_pass += 1 if ok else 0
        samples.append({"ok": bool(ok), "info": info,
                        "turns": len(rs),
                        "last": (rs[-1].get("content") or "")[:300],
                        "finish_reason": rs[-1].get("finish_reason"),
                        "tps": rs[-1].get("tps")})
    return n_pass, k, samples


def repeat_chat(model, prompt, grade, k=None, **kw):
    """同一道题跑 k 次、逐次判分，返回 (通过次数, k, 样本列表)。

    为什么必须重复：采样参数交给各模型的推荐设定之后温度不再是 0，
    **单次结果只是一次抽样** —— 一次对错说明不了问题，得看 k 次里对了几次。

    每次用不同 seed（SEED_BASE+1 .. SEED_BASE+k）：既拿到采样多样性，又尽量可复现
    （本地 llama.cpp 认 seed；云端多半忽略，那就纯随机，无妨）。

    grade 是 fn(resp) -> (bool, str)，由各用例自己给。
    """
    k = k or REPEAT
    n_pass, samples = 0, []
    for i in range(k):
        r = chat(model, prompt, seed=SEED_BASE + i + 1, **kw)
        if "error" in r:
            samples.append({"err": r["error"]})
            continue
        try:
            ok, info = grade(r)
        except Exception as e:                  # 判分器自己炸了，不该记成模型答错
            samples.append({"grader_error": str(e)[:200]})
            continue
        n_pass += 1 if ok else 0
        samples.append({"ok": bool(ok), "info": info,
                        "content": (r.get("content") or "")[:300],
                        "tool_calls": r.get("tool_calls"),
                        "finish_reason": r.get("finish_reason"),
                        "tps": r.get("tps")})
    return n_pass, k, samples


def _strip_latex(text):
    """把 LaTeX 数学记法压回普通文本，供关键词匹配用。

    起因（2026-08-17）：K4 问堆排序最坏复杂度，模型三次都答对，但其中两次写成
    `**$O(n \\log n)$**`，朴素子串匹配 `"n log n"` 匹配不到 `n \\log n`，**被判成答错**。
    这是 README 里写的「关键词判对错必有假阳性」的镜像 —— 假阴性，而且专坑
    「爱用 LaTeX 写数学」的模型，等于按输出风格而不是按对错给分。

    做的是纯记法归一化，**不放宽语义**：去掉数学定界符、把 `\\log` 之类的命令名
    还原成裸词、折叠空白。答案本身错的照样匹配不上。
    """
    s = text.replace("\\(", " ").replace("\\)", " ").replace("\\[", " ").replace("\\]", " ")
    s = re.sub(r"\\[,;:!]", " ", s)          # 间距命令 \, \; \: \!
    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)   # \log -> log, \times -> times
    s = s.replace("$", " ").replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", s)


def contains_kw(content, kws):
    """关键词判分统一入口：原文与 LaTeX 归一化后的文本，任一命中即算命中。

    保留原文匹配是为了**不破坏历史可比性** —— 旧口径能过的，新口径一定也过。
    """
    c = (content or "").lower()
    n = _strip_latex(c)
    return any(k.lower() in c or k.lower() in n for k in kws)


def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S)
    return m[0].strip() if m else text.strip()

# ── 模型代码的执行沙箱 ────────────────────────────────────────────────────
# run_code() / run_code_verdict() 跑的是**模型现写的 Python**，HC/X 两卷加起来几百次。
# 在宿主上直接跑，等于把一个 shell 交给被测模型：一句 shutil.rmtree 就能删掉家目录，
# 而它并不需要这份权限才能答对一道算法题 —— 代价极不对称，所以默认放进容器。
# （agent 卷那边模型有工具、有越狱的手，已经在容器里跑；裸卷不给工具，但**这一层**
#   是框架自己主动执行模型输出，同样得挡住。）
#
#   docker  --network none + 只读根 fs + 只挂一个临时目录，跑完即弃
#   host    历史行为：直接 subprocess 跑。docker 不可用时的兜底，会打印出来
#
# EVAL_CODE_SANDBOX=auto(默认，docker 可用就用) | docker | host
CODE_SANDBOX = os.environ.get("EVAL_CODE_SANDBOX", "auto")
CODE_IMAGE = os.environ.get("EVAL_DOCKER_IMAGE", "llm-eval-agent:1.18.29")
# 容器启动大约 0.3~0.5 秒。超时是给「算法本身跑多久」定的，不该被启动开销吃掉，
# 所以 docker 档统一补一点余量 —— 否则同一份代码在两档下的超时判定口径不一样。
CODE_STARTUP_GRACE = float(os.environ.get("EVAL_CODE_GRACE", "2"))
# 模型代码落在 /tmp 的临时目录，不再写进仓库的 bare_llm/（以前 _sol.py 就落在那儿）
CODE_TMP = tempfile.mkdtemp(prefix="barecode-")
atexit.register(lambda: shutil.rmtree(CODE_TMP, ignore_errors=True))

_CODE_MODE = None


def _pick_code_sandbox():
    """选一次、打印一次。与 agent 卷那边一样：绝不静默降级。"""
    global _CODE_MODE
    if _CODE_MODE:
        return _CODE_MODE
    mode = CODE_SANDBOX
    if mode == "auto":
        mode = "docker" if _code_docker_ok() else "host"
    if mode == "docker" and not _code_docker_ok():
        raise RuntimeError(f"EVAL_CODE_SANDBOX=docker 但 docker 或镜像 {CODE_IMAGE} 不可用；"
                           f"先 build（agent/docker/Dockerfile），或显式用 host 档。")
    if mode not in ("docker", "host"):
        raise RuntimeError(f"EVAL_CODE_SANDBOX 取值非法：{mode}")
    _CODE_MODE = mode
    note = {"docker": f"容器执行（{CODE_IMAGE}，--network none，只挂临时目录）",
            "host":   "★ 宿主直接执行 —— 模型代码拿的是当前用户的全部权限"}[mode]
    print(f"[隔离] 模型代码执行 = {mode}：{note}", flush=True)
    return mode


def _code_docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", CODE_IMAGE],
                              capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def _run_pyfile(path, timeout):
    """跑一个 .py 文件，返回 (completed_process 或 None, 是否超时)。

    docker 档下超时要**显式收掉容器** —— 杀 docker 客户端不等于容器停了，
    留着它继续跑会一直占着 CPU，还可能把后一道题的判分拖慢。
    """
    if _pick_code_sandbox() == "host":
        try:
            return subprocess.run([sys.executable, path], capture_output=True,
                                  timeout=timeout, text=True), False
        except subprocess.TimeoutExpired:
            return None, True
    name = f"barecode-{os.getpid()}-{os.urandom(3).hex()}"
    cmd = ["docker", "run", "--rm", "--init", "--name", name,
           "--network", "none",                       # 算法题不需要网络，断掉
           "--user", f"{os.getuid()}:{os.getgid()}",
           "--read-only", "--tmpfs", "/tmp:rw,exec,size=256m",
           "-v", f"{CODE_TMP}:{CODE_TMP}", "-w", CODE_TMP,
           "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
           CODE_IMAGE, "python3", path]
    try:
        return subprocess.run(cmd, capture_output=True,
                              timeout=timeout + CODE_STARTUP_GRACE, text=True), False
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=120)
        return None, True


def run_code(code, test):
    """把模型代码 + 测试拼到一起跑，退出码 0 = 通过。隔离子进程、15s 超时。"""
    f = os.path.join(CODE_TMP, "_sol.py")
    with open(f, "w") as fh:
        fh.write(code + "\n\n# ---- test ----\n" + test + "\nprint('ALL_PASS')\n")
    try:
        r, timed_out = _run_pyfile(f, 15)
        if timed_out:
            return False, "TIMEOUT"
        ok = (r.returncode == 0 and "ALL_PASS" in r.stdout)
        return ok, (r.stderr or r.stdout)[-300:].strip()
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
    f = os.path.join(CODE_TMP, "_sol_verdict.py")
    with open(f, "w") as fh:
        fh.write(runner)
    try:
        r, timed_out = _run_pyfile(f, timeout)
    except Exception as e:
        v.grader_error = f"子进程异常: {e}"
        return v
    if timed_out:
        v.f2p_total = n_assert                      # 一条都没过
        return v.p2p_add(False).note("TIMEOUT")

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
