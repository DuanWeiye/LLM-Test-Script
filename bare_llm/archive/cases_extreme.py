#!/usr/bin/env python3
"""EXTREME 卷：以「拉开模型差距」为目标的高难题。

**为什么还要更难**：DENSE 卷（cases_dense.py）的难度来源是「需求点多」，但每个点本身
用 if/else 就能覆盖 —— 地板模型 qwen3.6-35b 仔细读题就能过 63%，天花板模型必然 100%，
测不出差距。

本卷的难度来源换成三样，都是朴素实现必错的：
  1. **算法本身有陷阱**：正确解需要先想清楚结构，堆分支堆不出来；
  2. **多机制相互作用**：单看每条规则都简单，凑在一起会互相干扰（顾此失彼）；
  3. **要求产出诊断信息**：不只是「检测到错误」，还要报出**具体是哪条路径/哪一列**，
     这是绝大多数实现会偷懒省掉的部分。

题目自出，未搬运任何基准的任务集。格式同 HC/DENSE：(id, lang, prompt, test, forbid)。
"""

EXTREME = [
    ("HX1", "CN",
     "实现 `def schedule(tasks):`，对带依赖的任务排出执行顺序。"
     "tasks 是列表，每项形如 `{'id': str, 'priority': int, 'deps': [id, ...]}`。规则："
     "结果必须满足依赖（每个任务出现在它所有依赖之后）；"
     "**在所有依赖都已满足的候选中，优先取 priority 大的**；"
     "priority 相同时，按该任务在输入列表里的**原始顺序**取（稳定）；"
     "依赖了不存在的 id 时抛 ValueError，消息里要包含那个缺失的 id；"
     "**存在环时抛 ValueError，且消息必须形如 `cycle: a -> b -> a`** —— "
     "要给出环上真实的节点序列、首尾为同一节点，起点规范化为**环上字典序最小的那个 id**，"
     "并沿依赖方向（被依赖者在前）输出；"
     "输入为空列表返回空列表。只给代码。",
     """
r = schedule([{'id': 'a', 'priority': 1, 'deps': []},
              {'id': 'b', 'priority': 5, 'deps': []},
              {'id': 'c', 'priority': 3, 'deps': ['a', 'b']}])
assert r == ['b', 'a', 'c'], r
r = schedule([{'id': 'x', 'priority': 1, 'deps': []},
              {'id': 'y', 'priority': 1, 'deps': []},
              {'id': 'z', 'priority': 1, 'deps': []}])
assert r == ['x', 'y', 'z'], r
r = schedule([{'id': 'lo', 'priority': 0, 'deps': []},
              {'id': 'hi', 'priority': 9, 'deps': ['lo']}])
assert r == ['lo', 'hi'], r
assert schedule([]) == []
r = schedule([{'id': 'a', 'priority': 1, 'deps': []},
              {'id': 'b', 'priority': 2, 'deps': ['a']},
              {'id': 'c', 'priority': 3, 'deps': ['a']},
              {'id': 'd', 'priority': 9, 'deps': ['b', 'c']}])
assert r == ['a', 'c', 'b', 'd'], r
try:
    schedule([{'id': 'a', 'priority': 1, 'deps': ['ghost']}])
    raise AssertionError('应抛 ValueError')
except ValueError as _e:
    assert 'ghost' in str(_e)
try:
    schedule([{'id': 'b', 'priority': 1, 'deps': ['a']},
              {'id': 'a', 'priority': 1, 'deps': ['b']}])
    raise AssertionError('应抛 ValueError')
except ValueError as _e:
    assert 'cycle: a -> b -> a' in str(_e), str(_e)
try:
    schedule([{'id': 'q', 'priority': 1, 'deps': ['p']},
              {'id': 'p', 'priority': 1, 'deps': ['r']},
              {'id': 'r', 'priority': 1, 'deps': ['q']}])
    raise AssertionError('应抛 ValueError')
except ValueError as _e:
    assert 'cycle: p -> r -> q -> p' in str(_e), str(_e)
""", None),

    ("HX2", "CN",
     "实现 `def evaluate(expr: str) -> float:`，求值中缀算术表达式。规则："
     "支持 `+ - * / ** ( )` 与十进制数（可含小数点）；"
     "优先级：`**` 最高，其次 `* /`，最后 `+ -`；"
     "**`**` 是右结合**（`2**3**2` 等于 512 而不是 64），其余二元运算左结合；"
     "支持一元正负号，且**一元负号的优先级低于 `**`**（`-2**2` 等于 -4），"
     "但高于乘除（`-2*3` 等于 -6）；连续一元号合法（`--3` 等于 3）；"
     "除以零抛 ZeroDivisionError；"
     "遇到非法字符、括号不匹配、或运算符位置不对时抛 ValueError，"
     "**消息里必须包含 `col=N`**，N 是出错处在原字符串中从 1 开始的列号；"
     "空白字符可出现在任意位置且应被忽略（但不影响列号计算）。只给代码。",
     """
assert evaluate('1+2*3') == 7
assert evaluate('(1+2)*3') == 9
assert evaluate('2**3**2') == 512
assert evaluate('-2**2') == -4
assert evaluate('-2*3') == -6
assert evaluate('--3') == 3
assert evaluate(' 1 + 2 ') == 3
assert abs(evaluate('7/2') - 3.5) < 1e-9
try:
    evaluate('1/0')
    raise AssertionError('应抛 ZeroDivisionError')
except ZeroDivisionError:
    pass
try:
    evaluate('1+@')
    raise AssertionError('应抛 ValueError')
except ValueError as _e:
    assert 'col=3' in str(_e), str(_e)
try:
    evaluate('(1+2')
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
try:
    evaluate('1++')
    raise AssertionError('应抛 ValueError')
except ValueError:
    pass
""", None),

    ("HX3", "CN",
     "实现复合缓存 `Cache`：`__init__(self, max_weight)`，"
     "`put(self, key, value, weight=1, ttl=None, now=0.0)`，`get(self, key, now=0.0)`，"
     "以及只读属性 `hits` / `misses` / `evictions` / `expirations`。规则："
     "按 **weight 总和**限容（不是条数），放入后若超出 max_weight 则按 **LRU 顺序**淘汰"
     "直到不超（get 与 put 都算一次使用）；"
     "**单项 weight 超过 max_weight 时直接拒绝存入**（不淘汰任何already存在的项，也不计 evictions）；"
     "ttl 为 None 表示永不过期，否则在 `now + ttl` 之后过期；"
     "**过期项 get 时算 miss、要计入 expirations 并从缓存中移除**（惰性清理），"
     "**且过期不算 evictions**；"
     "重复 put 同一个 key 视为更新（替换 value/weight/ttl 并刷新为最近使用），不计 evictions；"
     "get 未命中返回 None；max_weight 小于等于 0 抛 ValueError。只给代码。",
     """
c = Cache(10)
c.put('a', 1, weight=4, now=0.0)
c.put('b', 2, weight=4, now=0.0)
assert c.get('a', now=0.0) == 1
c.put('c', 3, weight=4, now=0.0)
assert c.get('b', now=0.0) is None
assert c.get('a', now=0.0) == 1 and c.get('c', now=0.0) == 3
assert c.evictions == 1, c.evictions
c2 = Cache(10)
c2.put('big', 1, weight=99, now=0.0)
assert c2.get('big', now=0.0) is None
assert c2.evictions == 0, c2.evictions
c3 = Cache(10)
c3.put('t', 1, weight=1, ttl=5.0, now=0.0)
assert c3.get('t', now=4.9) == 1
assert c3.get('t', now=5.1) is None
assert c3.expirations == 1 and c3.evictions == 0
assert c3.get('t', now=6.0) is None
assert c3.expirations == 1, c3.expirations
c4 = Cache(10)
c4.put('k', 1, weight=3, now=0.0)
c4.put('k', 2, weight=3, now=0.0)
assert c4.get('k', now=0.0) == 2 and c4.evictions == 0
c5 = Cache(4)
c5.put('x', 1, weight=2, now=0.0)
c5.put('y', 2, weight=2, now=0.0)
c5.get('x', now=0.0)
c5.put('z', 3, weight=2, now=0.0)
assert c5.get('y', now=0.0) is None and c5.get('x', now=0.0) == 1
assert c5.hits >= 2 and c5.misses >= 1
""", None),
]


EXTREME_ORACLES = {
    "HX1": '''
def schedule(tasks):
    order = [t["id"] for t in tasks]
    index = {tid: i for i, tid in enumerate(order)}
    by_id = {t["id"]: t for t in tasks}
    for t in tasks:
        for d in t["deps"]:
            if d not in by_id:
                raise ValueError(f"任务 {t['id']} 依赖了不存在的 id: {d}")

    remaining = {t["id"]: set(t["deps"]) for t in tasks}
    out = []
    while remaining:
        ready = [tid for tid, deps in remaining.items() if not deps]
        if not ready:
            raise ValueError(_describe_cycle(remaining))
        # 依赖都满足的候选里：priority 大优先，其次按原始输入顺序（稳定）
        ready.sort(key=lambda tid: (-by_id[tid]["priority"], index[tid]))
        pick = ready[0]
        out.append(pick)
        del remaining[pick]
        for deps in remaining.values():
            deps.discard(pick)
    return out


def _describe_cycle(remaining):
    """在剩余图里找一个真实的环，起点规范化为环上字典序最小的节点。"""
    # 每个节点指向它依赖的节点；沿 deps 走必然进环
    for start in sorted(remaining):
        seen, path, cur = {}, [], start
        while cur in remaining and cur not in seen:
            seen[cur] = len(path)
            path.append(cur)
            nxt = sorted(remaining[cur])
            if not nxt:
                break
            cur = nxt[0]
        if cur in seen:
            cyc = path[seen[cur]:]
            m = min(range(len(cyc)), key=lambda i: cyc[i])
            cyc = cyc[m:] + cyc[:m]     # 起点规范化为环上字典序最小的节点
            # 路径本身就是依赖方向（a -> b 表示 a 依赖 b），无需反转
            return "cycle: " + " -> ".join(cyc + [cyc[0]])
    return "cycle: <unknown>"
''',

    "HX2": '''
def evaluate(expr):
    toks = _tokenize(expr)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def expect_end():
        t = peek()
        if t is not None:
            raise ValueError(f"多余的输入 col={t[2]}")

    def parse_expr():
        node = parse_term()
        while True:
            t = peek()
            if t and t[0] == "op" and t[1] in "+-":
                pos[0] += 1
                rhs = parse_term()
                node = node + rhs if t[1] == "+" else node - rhs
            else:
                return node

    def parse_term():
        node = parse_unary()
        while True:
            t = peek()
            if t and t[0] == "op" and t[1] in "*/":
                pos[0] += 1
                rhs = parse_unary()
                if t[1] == "*":
                    node = node * rhs
                else:
                    if rhs == 0:
                        raise ZeroDivisionError("除以零")
                    node = node / rhs
            else:
                return node

    def parse_unary():
        t = peek()
        if t and t[0] == "op" and t[1] in "+-":
            pos[0] += 1
            val = parse_unary()          # 一元号优先级低于 **，故递归到 unary
            return -val if t[1] == "-" else val
        return parse_power()

    def parse_power():
        base = parse_atom()
        t = peek()
        if t and t[0] == "op" and t[1] == "**":
            pos[0] += 1
            exp = parse_unary()          # 右结合，且允许 2**-1
            return base ** exp
        return base

    def parse_atom():
        t = peek()
        if t is None:
            raise ValueError(f"表达式意外结束 col={len(expr) + 1}")
        if t[0] == "num":
            pos[0] += 1
            return t[1]
        if t[0] == "lp":
            pos[0] += 1
            val = parse_expr()
            nt = peek()
            if nt is None or nt[0] != "rp":
                raise ValueError(f"括号不匹配 col={t[2]}")
            pos[0] += 1
            return val
        raise ValueError(f"意外的记号 col={t[2]}")

    val = parse_expr()
    expect_end()
    return val


def _tokenize(s):
    toks, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        col = i + 1
        if ch.isdigit() or ch == ".":
            j = i
            dots = 0
            while j < n and (s[j].isdigit() or s[j] == "."):
                if s[j] == ".":
                    dots += 1
                j += 1
            text = s[i:j]
            if dots > 1:
                raise ValueError(f"非法数字 col={col}")
            toks.append(("num", float(text) if "." in text else int(text), col))
            i = j
            continue
        if s.startswith("**", i):
            toks.append(("op", "**", col))
            i += 2
            continue
        if ch in "+-*/":
            toks.append(("op", ch, col))
            i += 1
            continue
        if ch == "(":
            toks.append(("lp", ch, col))
            i += 1
            continue
        if ch == ")":
            toks.append(("rp", ch, col))
            i += 1
            continue
        raise ValueError(f"非法字符 {ch!r} col={col}")
    return toks
''',

    "HX3": '''
from collections import OrderedDict


class Cache:
    def __init__(self, max_weight):
        if max_weight <= 0:
            raise ValueError("max_weight 必须为正")
        self.max_weight = max_weight
        self._d = OrderedDict()          # key -> [value, weight, expire_at or None]
        self._w = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    def _drop(self, key):
        _, w, _ = self._d.pop(key)
        self._w -= w

    def put(self, key, value, weight=1, ttl=None, now=0.0):
        if weight > self.max_weight:     # 单项超容：直接拒绝，不淘汰别人
            return
        if key in self._d:
            self._drop(key)
        exp = None if ttl is None else now + ttl
        self._d[key] = [value, weight, exp]
        self._w += weight
        while self._w > self.max_weight:
            old = next(iter(self._d))
            self._drop(old)
            self.evictions += 1

    def get(self, key, now=0.0):
        item = self._d.get(key)
        if item is None:
            self.misses += 1
            return None
        value, _, exp = item
        if exp is not None and now > exp:
            self._drop(key)              # 过期属于 expirations，不算 evictions
            self.expirations += 1
            self.misses += 1
            return None
        self._d.move_to_end(key)         # get 也算一次使用
        self.hits += 1
        return value
''',
}
