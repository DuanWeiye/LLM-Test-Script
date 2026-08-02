#!/usr/bin/env python3
"""高需求密度编码题（DENSE 卷）+ 参考解。

**为什么加这一卷**：原有编码题（two_sum / quicksort / rle_encode…）是单一功能、零边界、
零交互，本地这一档模型基本都能过，区分不出高低。

**设计参考 DeepSWE 的题目形态，但题目是自己出的**（DeepSWE 任务集带 canary GUID 并明确
要求不得进入训练语料，不能搬运）。借的是它「简单题」的三个结构特征：

  1. 题面短，但**每个词都是需求** —— 一句话塞一个约束，不展开解释；
  2. 正常路径一句带过，**边界与错误处理占主体**（抛什么异常、消息里要有什么）；
  3. 需求之间**相互关联**（选项互斥、与既有行为交互、状态在多次调用间保持）。

四道题都是日常业务里真会写的东西（版本比较、配置合并、限流、日志解析），不是算法玩具。
每道 7~9 条断言覆盖不同边界，配合 run_code_verdict 的逐条计分 → partial 有区分度：
「主功能对了但边界全错」和「完全不会」不再都是 0 分。

格式与 full_eval_hard.py 的 HC 一致：(id, lang, prompt, test, forbid)。
"""

DENSE = [
    ("HD1", "CN",
     "实现 `def compare_versions(a: str, b: str) -> int:`，比较两个语义化版本号，"
     "a 大返回 1、b 大返回 -1、相等返回 0。规则："
     "版本主体是点分数字段，**按数值比较而非字典序**（1.10.0 > 1.9.0）；"
     "段数不足的按 0 补齐（1.0 等于 1.0.0）；"
     "主体后可跟 `-预发布`，**有预发布的小于没有预发布的**同主体版本；"
     "预发布部分再按点分段逐段比较，**纯数字段按数值比、含非数字的段按字典序比、"
     "数字段小于字母段**；段数不足的一方更小；"
     "版本还可带 `+构建元数据`，比较时**完全忽略**；"
     "输入为空串或主体含非数字字符时抛 ValueError。只给代码。",
     """
assert compare_versions('1.0.0', '1.0.0') == 0
assert compare_versions('1.10.0', '1.9.0') == 1
assert compare_versions('1.0', '1.0.0') == 0
assert compare_versions('1.0.0-alpha', '1.0.0') == -1
assert compare_versions('1.0.0-alpha.1', '1.0.0-alpha.2') == -1
assert compare_versions('1.0.0-alpha.9', '1.0.0-alpha.10') == -1
assert compare_versions('1.0.0-1', '1.0.0-alpha') == -1
assert compare_versions('1.0.0-alpha', '1.0.0-alpha.1') == -1
assert compare_versions('1.0.0+build1', '1.0.0+build2') == 0
try:
    compare_versions('', '1.0.0')
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
""", None),

    ("HD2", "CN",
     "实现 `def merge_config(base: dict, override: dict) -> dict:`，深合并两份配置并返回**新字典**。规则："
     "两边同名 key 都是 dict 时递归合并；"
     "override 里某个 key 的值是 None 表示**删除**该 key（base 里没有则忽略，且结果里不该出现这个 key）；"
     "override 里 key 以 `+` 开头表示**追加**：去掉加号后与 base 的同名 list 拼接（base 没有该 key 时等价于直接赋值）；"
     "普通同名 list 是**整体替换**不是追加；"
     "一边是 dict 另一边不是 dict 时抛 TypeError，且异常消息里要包含出问题的**点分路径**（如 `a.b`）；"
     "**不得修改传入的 base 和 override**；"
     "结果保持 base 原有 key 顺序，base 里没有的新 key 按 override 顺序追加在后面。只给代码。",
     """
assert merge_config({'a': 1}, {'b': 2}) == {'a': 1, 'b': 2}
assert merge_config({'a': {'x': 1, 'y': 2}}, {'a': {'y': 3}}) == {'a': {'x': 1, 'y': 3}}
assert merge_config({'a': 1, 'b': 2}, {'a': None}) == {'b': 2}
assert merge_config({'l': [1, 2]}, {'+l': [3]}) == {'l': [1, 2, 3]}
assert merge_config({'l': [1, 2]}, {'l': [9]}) == {'l': [9]}
assert merge_config({}, {'+l': [1]}) == {'l': [1]}
_b = {'a': {'x': 1}}
merge_config(_b, {'a': {'x': 2}})
assert _b == {'a': {'x': 1}}
try:
    merge_config({'a': {'b': {'c': 1}}}, {'a': {'b': 5}})
    raise AssertionError('应抛 TypeError')
except TypeError as _e:
    assert 'a.b' in str(_e)
assert list(merge_config({'a': 1, 'b': 2}, {'c': 3, 'a': 9})) == ['a', 'b', 'c']
""", None),

    ("HD3", "CN",
     "实现令牌桶限流类 `TokenBucket`：`__init__(self, capacity, refill_rate, now=0.0)`，"
     "`consume(self, n=1, now=None) -> tuple[bool, float]`。规则："
     "桶初始装满 capacity 个令牌；按 refill_rate（个/秒）随时间补充，"
     "**补充上限为 capacity 不得溢出**；"
     "consume 成功返回 `(True, 0.0)` 并扣减；"
     "**令牌不足时不扣减任何令牌**，返回 `(False, 还需等待的秒数)`，等待秒数按当前速率算到刚好够 n 个为止；"
     "传入的 now 比上次记录的时间**更早时（时钟回拨）不得补充令牌**，也不能报错；"
     "now 为 None 时沿用上次的时间；"
     "capacity 或 refill_rate 小于等于 0、或 n 小于等于 0 时抛 ValueError。只给代码。",
     """
b = TokenBucket(2, 1.0, now=0.0)
assert b.consume(1, now=0.0) == (True, 0.0)
assert b.consume(1, now=0.0) == (True, 0.0)
_ok, _wait = b.consume(1, now=0.0)
assert _ok is False and abs(_wait - 1.0) < 1e-6
assert b.consume(1, now=1.0)[0] is True
b2 = TokenBucket(2, 1.0, now=0.0)
b2.consume(2, now=0.0)
assert b2.consume(2, now=100.0)[0] is True
assert b2.consume(1, now=100.0)[0] is False
b3 = TokenBucket(2, 1.0, now=10.0)
b3.consume(2, now=10.0)
assert b3.consume(1, now=5.0)[0] is False
b4 = TokenBucket(5, 1.0, now=0.0)
b4.consume(5, now=0.0)
_ok4, _w4 = b4.consume(3, now=0.0)
assert _ok4 is False and abs(_w4 - 3.0) < 1e-6
assert b4.consume(1, now=0.0)[0] is False
try:
    TokenBucket(0, 1.0)
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
""", None),

    ("HD4", "CN",
     "实现 `def parse_logfmt(line: str) -> dict:`，解析 logfmt 风格的日志行。规则："
     "字段以空格分隔，形如 `key=value`；"
     "值可以用双引号包裹，**引号内的空格属于值本身**，引号内的 `\\\"` 是转义的双引号、`\\\\` 是反斜杠；"
     "**没有等号的裸 token** 视为布尔标志，其值为 True（不是字符串）；"
     "**同名 key 出现多次时，值收集成按出现顺序排列的 list**（只出现一次时不要包成 list）；"
     "多个连续空格等同一个；空串返回空字典；"
     "引号未闭合时抛 ValueError。只给代码。",
     r"""
assert parse_logfmt('a=1 b=2') == {'a': '1', 'b': '2'}
assert parse_logfmt('msg="hello world"') == {'msg': 'hello world'}
assert parse_logfmt(r'msg="say \"hi\""') == {'msg': 'say "hi"'}
assert parse_logfmt('debug a=1') == {'debug': True, 'a': '1'}
assert parse_logfmt('k=1 k=2 k=3') == {'k': ['1', '2', '3']}
assert parse_logfmt('') == {}
assert parse_logfmt('a=1    b=2') == {'a': '1', 'b': '2'}
assert parse_logfmt('a=') == {'a': ''}
try:
    parse_logfmt('a="unclosed')
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
""", None),
    ("HD5", "CN",
     "实现路由匹配器 `Router`：`add(self, pattern, handler)` 与 `match(self, path) -> tuple`。规则："
     "pattern 由 `/` 分段，段可以是静态文本、`:name`（捕获单段）、`*name`（捕获剩余全部段，只能出现在末尾）；"
     "match 返回 `(handler, 参数字典)`，无匹配返回 `(None, {})`；"
     "**同一位置上优先级为 静态 > :name > *name**，即静态段能匹配时不得选参数路由，"
     "且该优先级要**逐段**判断（前缀相同时看后续段谁更具体）；"
     "`*name` 捕获的值是**剩余路径原样拼接的字符串**（不含前导斜杠），可以为空串；"
     "路径与 pattern 都要先归一化：去掉尾部斜杠、把连续多个斜杠折叠成一个（根路径 `/` 除外）；"
     "重复注册完全相同的 pattern 抛 ValueError；`*` 不在末尾抛 ValueError。只给代码。",
     """
r = Router()
r.add('/users/list', 'static')
r.add('/users/:id', 'param')
r.add('/files/*rest', 'splat')
r.add('/', 'root')
assert r.match('/users/list') == ('static', {})
assert r.match('/users/42') == ('param', {'id': '42'})
assert r.match('/files/a/b/c') == ('splat', {'rest': 'a/b/c'})
assert r.match('/files') == ('splat', {'rest': ''})
assert r.match('/') == ('root', {})
assert r.match('/users/list/') == ('static', {})
assert r.match('//users//42') == ('param', {'id': '42'})
assert r.match('/nope/x') == (None, {})
r2 = Router()
r2.add('/a/:x/c', 'p')
r2.add('/a/b/c', 's')
assert r2.match('/a/b/c') == ('s', {})
assert r2.match('/a/z/c') == ('p', {'x': 'z'})
try:
    r2.add('/a/b/c', 'dup')
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
try:
    Router().add('/x/*mid/y', 'bad')
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
""", None),

    ("HD6", "CN",
     "实现支持**嵌套事务**的键值存储 `TxStore`：`get(k)` / `set(k, v)` / `delete(k)` / "
     "`begin()` / `commit()` / `rollback()`。规则："
     "未 begin 时读写直接作用于底层存储；"
     "begin 开启一层事务，可嵌套；set/delete 只写入**当前最内层**；"
     "get 要**从最内层向外逐层查找**，遇到该层删除标记则返回 None（不再继续往外找）；"
     "键不存在时 get 返回 None；"
     "rollback 丢弃当前层的全部改动、回到上一层；"
     "commit 把当前层的改动（含删除标记）**合并进上一层**，而不是直接落到底层；"
     "没有活动事务时调用 commit 或 rollback 抛 RuntimeError。只给代码。",
     """
s = TxStore()
s.set('a', 1)
assert s.get('a') == 1
assert s.get('nope') is None
s.begin()
s.set('a', 2)
s.set('b', 3)
assert s.get('a') == 2
s.rollback()
assert s.get('a') == 1 and s.get('b') is None
s.begin()
s.set('b', 9)
s.begin()
s.set('b', 10)
s.delete('a')
assert s.get('b') == 10 and s.get('a') is None
s.rollback()
assert s.get('b') == 9 and s.get('a') == 1
s.commit()
assert s.get('b') == 9
s.begin()
s.delete('a')
s.commit()
assert s.get('a') is None
try:
    s.commit()
    raise AssertionError('应抛 RuntimeError')
except RuntimeError:
    pass
""", None),
    ("HD7", "CN",
     "实现 `def daily_buckets(timestamps, tz_offset_hours=9):`，把一批 UTC 时间戳按**本地时区的自然日**分桶计数。规则："
     "输入是 ISO8601 字符串列表，可能形如 `2026-06-30T15:00:00Z` 或 `2026-06-30T15:00:00+00:00`，两种都要支持；"
     "先按 tz_offset_hours 换算成本地时间，再取本地日期做桶（**注意跨日**：UTC 6/30 15:00 在 +9 时区是 7/1 的 00:00）；"
     "返回 `{本地日期字符串(YYYY-MM-DD): 条数}`，且**按日期升序**排列；"
     "tz_offset_hours 可以为负数或 0；"
     "输入列表为空返回空字典；"
     "时间串无法解析时抛 ValueError，消息里要包含那个非法字符串本身。只给代码。",
     """
r = daily_buckets(['2026-06-30T15:00:00Z'])
assert r == {'2026-07-01': 1}, r
r = daily_buckets(['2026-06-30T14:59:59Z', '2026-06-30T15:00:00Z'])
assert r == {'2026-06-30': 1, '2026-07-01': 1}, r
assert daily_buckets(['2026-06-30T15:00:00+00:00']) == {'2026-07-01': 1}
assert daily_buckets([]) == {}
assert daily_buckets(['2026-06-30T15:00:00Z'], tz_offset_hours=0) == {'2026-06-30': 1}
assert daily_buckets(['2026-07-01T02:00:00Z'], tz_offset_hours=-5) == {'2026-06-30': 1}
r = daily_buckets(['2026-07-02T00:00:00Z', '2026-06-30T15:00:00Z', '2026-07-01T00:00:00Z'])
assert list(r) == ['2026-07-01', '2026-07-02'], list(r)
assert r == {'2026-07-01': 2, '2026-07-02': 1}
try:
    daily_buckets(['not-a-time'])
    raise AssertionError('应抛 ValueError')
except ValueError as _e:
    assert 'not-a-time' in str(_e)
""", None),

    ("HD8", "CN",
     "实现重试器 `Retrier`：`__init__(self, max_attempts, base_delay, cap, sleep=None)` 与 `run(self, fn, *args)`。规则："
     "run 调用 fn，抛异常就重试，**最多尝试 max_attempts 次**（含第一次）；"
     "第 k 次失败后等待 `base_delay * 2**(k-1)` 秒，但**不超过 cap**；等待通过构造时传入的 sleep 函数完成（默认 time.sleep）；"
     "全部失败时**抛出最后一次的那个异常对象本身**（不要包装成别的异常）；"
     "成功时返回 fn 的返回值，并且**内部的尝试计数与累计等待必须复位**——"
     "下一次调用 run 要重新从第一次开始计算退避，不能沿用上一次的状态；"
     "暴露只读属性 `last_attempts`（上一次 run 实际尝试了几次）和 `total_slept`（上一次 run 累计等待秒数）；"
     "max_attempts 小于 1、base_delay 为负、cap 小于 base_delay 时抛 ValueError。只给代码。",
     """
slept = []
r = Retrier(4, 1.0, 5.0, sleep=slept.append)
calls = {'n': 0}
def flaky():
    calls['n'] += 1
    if calls['n'] < 3:
        raise RuntimeError('boom')
    return 'ok'
assert r.run(flaky) == 'ok'
assert calls['n'] == 3
assert r.last_attempts == 3
assert slept == [1.0, 2.0], slept
assert abs(r.total_slept - 3.0) < 1e-9
slept.clear()
calls['n'] = 0
assert r.run(flaky) == 'ok'
assert slept == [1.0, 2.0], slept
assert r.last_attempts == 3
slept.clear()
r2 = Retrier(3, 4.0, 5.0, sleep=slept.append)
err = ValueError('always')
def always():
    raise err
try:
    r2.run(always)
    raise AssertionError('应抛出最后一次异常')
except ValueError as _e:
    assert _e is err
assert slept == [4.0, 5.0], slept
try:
    Retrier(0, 1.0, 2.0)
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
""", None),
]


# ---------- 参考解：真正正确的实现，供 selfcheck.py 验证题目/断言本身没写错 ----------
DENSE_ORACLES = {
    "HD1": '''
def _split_version(v):
    if not isinstance(v, str) or not v:
        raise ValueError("版本号不能为空")
    core = v.split("+", 1)[0]          # 构建元数据完全忽略
    if "-" in core:
        main, pre = core.split("-", 1)
    else:
        main, pre = core, None
    parts = main.split(".")
    if not all(p.isdigit() and p != "" for p in parts):
        raise ValueError(f"非法版本主体: {main}")
    return [int(p) for p in parts], pre


def _cmp(x, y):
    return (x > y) - (x < y)


def _cmp_pre(a, b):
    """预发布段比较：数字段按数值、字母段按字典序、数字段小于字母段。"""
    ap = a.split(".") if a else []
    bp = b.split(".") if b else []
    for i in range(max(len(ap), len(bp))):
        if i >= len(ap):
            return -1                   # 段数少的更小
        if i >= len(bp):
            return 1
        x, y = ap[i], bp[i]
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            c = _cmp(int(x), int(y))
        elif xd != yd:
            return -1 if xd else 1      # 数字段 < 字母段
        else:
            c = _cmp(x, y)
        if c:
            return c
    return 0


def compare_versions(a, b):
    na, pa = _split_version(a)
    nb, pb = _split_version(b)
    n = max(len(na), len(nb))
    na = na + [0] * (n - len(na))       # 段数不足补 0
    nb = nb + [0] * (n - len(nb))
    c = _cmp(na, nb)
    if c:
        return c
    if pa is None and pb is None:
        return 0
    if pa is None:
        return 1                        # 无预发布 > 有预发布
    if pb is None:
        return -1
    return _cmp_pre(pa, pb)
''',

    "HD2": '''
import copy


def _merge(base, override, path):
    out = {}
    drop = {k for k, v in override.items() if v is None}
    for k, v in base.items():
        if k in drop:
            continue
        out[k] = copy.deepcopy(v)
    for k, v in override.items():
        if v is None:
            continue
        cur_path = f"{path}.{k}" if path else k
        if isinstance(k, str) and k.startswith("+"):
            real = k[1:]
            old = out.get(real, [])
            out[real] = list(old) + list(v)
            continue
        if k in out:
            a, b = out[k], v
            if isinstance(a, dict) != isinstance(b, dict):
                raise TypeError(f"类型冲突于 {cur_path}: {type(a).__name__} vs {type(b).__name__}")
            if isinstance(a, dict):
                out[k] = _merge(a, b, cur_path)
                continue
        out[k] = copy.deepcopy(v)
    return out


def merge_config(base, override):
    return _merge(base, override, "")
''',

    "HD3": '''
class TokenBucket:
    def __init__(self, capacity, refill_rate, now=0.0):
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("capacity 与 refill_rate 必须为正")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last = float(now)

    def _refill(self, now):
        if now is None:
            return
        now = float(now)
        if now <= self.last:            # 时钟回拨：不补充也不报错
            self.last = min(self.last, now) if False else self.last
            return
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill_rate)
        self.last = now

    def consume(self, n=1, now=None):
        if n <= 0:
            raise ValueError("n 必须为正")
        self._refill(now)
        if self.tokens >= n:
            self.tokens -= n
            return (True, 0.0)
        need = n - self.tokens          # 不足时不扣减
        return (False, need / self.refill_rate)
''',

    "HD4": '''
def _tokenize(line):
    toks, buf, i, n = [], [], 0, len(line)
    in_q = False
    while i < n:
        ch = line[i]
        if in_q:
            if ch == "\\\\" and i + 1 < n and line[i + 1] in '"\\\\':
                buf.append(line[i + 1])
                i += 2
                continue
            if ch == '"':
                in_q = False
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_q = True
            i += 1
            continue
        if ch == " ":
            if buf:
                toks.append("".join(buf))
                buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if in_q:
        raise ValueError("引号未闭合")
    if buf:
        toks.append("".join(buf))
    return toks


def parse_logfmt(line):
    out = {}
    order = []
    for tok in _tokenize(line):
        if "=" in tok:
            k, v = tok.split("=", 1)
        else:
            k, v = tok, True
        if k in out:
            if not isinstance(out[k], list) or k not in order:
                out[k] = [out[k]]
                order.append(k)
            out[k].append(v)
        else:
            out[k] = v
    return out
''',

    "HD5": '''
class Router:
    def __init__(self):
        self.routes = []
        self._seen = set()

    @staticmethod
    def _norm(p):
        parts = [seg for seg in p.split("/") if seg != ""]
        return parts

    def add(self, pattern, handler):
        parts = self._norm(pattern)
        for i, seg in enumerate(parts):
            if seg.startswith("*") and i != len(parts) - 1:
                raise ValueError("* 只能出现在末尾")
        key = "/".join(parts)
        if key in self._seen:
            raise ValueError(f"重复注册: {pattern}")
        self._seen.add(key)
        self.routes.append((parts, handler))

    def match(self, path):
        parts = self._norm(path)
        best = None
        for pat, handler in self.routes:
            params, score = self._try(pat, parts)
            if params is None:
                continue
            if best is None or score > best[0]:
                best = (score, handler, params)
        if best is None:
            return (None, {})
        return (best[1], best[2])

    @staticmethod
    def _try(pat, parts):
        """返回 (params, 优先级元组)。静态=2 > :param=1 > *splat=0，逐段比较。"""
        params, score = {}, []
        for i, seg in enumerate(pat):
            if seg.startswith("*"):
                params[seg[1:]] = "/".join(parts[i:])
                score.append(0)
                return params, tuple(score)
            if i >= len(parts):
                return None, ()
            if seg.startswith(":"):
                params[seg[1:]] = parts[i]
                score.append(1)
            elif seg == parts[i]:
                score.append(2)
            else:
                return None, ()
        if len(parts) != len(pat):
            return None, ()
        return params, tuple(score)
''',

    "HD6": '''
_DELETED = object()


class TxStore:
    def __init__(self):
        self.base = {}
        self.stack = []

    def begin(self):
        self.stack.append({})

    def set(self, k, v):
        (self.stack[-1] if self.stack else self.base)[k] = v

    def delete(self, k):
        if self.stack:
            self.stack[-1][k] = _DELETED
        else:
            self.base.pop(k, None)

    def get(self, k):
        for layer in reversed(self.stack):
            if k in layer:
                val = layer[k]
                return None if val is _DELETED else val
        return self.base.get(k)

    def rollback(self):
        if not self.stack:
            raise RuntimeError("没有活动事务")
        self.stack.pop()

    def commit(self):
        if not self.stack:
            raise RuntimeError("没有活动事务")
        layer = self.stack.pop()
        if self.stack:
            self.stack[-1].update(layer)
        else:
            for k, v in layer.items():
                if v is _DELETED:
                    self.base.pop(k, None)
                else:
                    self.base[k] = v
''',

    "HD7": '''
from datetime import datetime, timedelta


def daily_buckets(timestamps, tz_offset_hours=9):
    counts = {}
    for ts in timestamps:
        raw = ts
        try:
            t = ts.strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            dt = datetime.fromisoformat(t)
        except Exception:
            raise ValueError(f"无法解析的时间戳: {raw}")
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None) - (dt.utcoffset() or timedelta(0))
        local = dt + timedelta(hours=tz_offset_hours)
        key = local.strftime("%Y-%m-%d")
        counts[key] = counts.get(key, 0) + 1
    return {k: counts[k] for k in sorted(counts)}
''',

    "HD8": '''
import time


class Retrier:
    def __init__(self, max_attempts, base_delay, cap, sleep=None):
        if max_attempts < 1 or base_delay < 0 or cap < base_delay:
            raise ValueError("参数非法")
        self.max_attempts = max_attempts
        self.base_delay = float(base_delay)
        self.cap = float(cap)
        self._sleep = sleep if sleep is not None else time.sleep
        self.last_attempts = 0
        self.total_slept = 0.0

    def run(self, fn, *args):
        self.last_attempts = 0          # 每次进来先复位，别沿用上一轮状态
        self.total_slept = 0.0
        last_exc = None
        for k in range(1, self.max_attempts + 1):
            self.last_attempts = k
            try:
                return fn(*args)
            except Exception as exc:
                last_exc = exc
                if k == self.max_attempts:
                    break
                delay = min(self.base_delay * (2 ** (k - 1)), self.cap)
                self.total_slept += delay
                self._sleep(delay)
        raise last_exc
''',
}

