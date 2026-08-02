#!/usr/bin/env python3
"""各编码用例的参考解 —— 供 selfcheck.py 验证「题目自带的 test 本身是对的」。

为什么需要：如果某道题的 test 写错了（比如期望值算错、断言引用了题面没要求的行为），
所有模型都会挂在那一条上，而你无从分辨是「模型都不行」还是「题出错了」。
DeepSWE 的 `--agent oracle` 就是干这个的，跑一遍参考解，全绿才说明评测框架自身健康。

这些实现是**真正正确的解**，不是为了迎合断言拼凑的 —— 判分才有意义。
"""

ORACLES = {
    "A1": """
def two_sum(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return []
""",
    "A2": """
def is_balanced(s):
    pairs = {')': '(', ']': '[', '}': '{'}
    stack = []
    for ch in s:
        if ch in '([{':
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
""",
    "A3": """
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key):
        if key not in self.data:
            return -1
        self.data.move_to_end(key)
        return self.data[key]

    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        self.data[key] = value
        if len(self.data) > self.capacity:
            self.data.popitem(last=False)
""",
    "A4": """
def first_index(arr, target):
    lo, hi, ans = 0, len(arr) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            ans = mid
            hi = mid - 1
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return ans
""",
    "A5": """
def quicksort(a):
    if len(a) <= 1:
        return list(a)
    pivot = a[len(a) // 2]
    less = [x for x in a if x < pivot]
    equal = [x for x in a if x == pivot]
    greater = [x for x in a if x > pivot]
    return quicksort(less) + equal + quicksort(greater)
""",
    "A6": """
def merge_intervals(intervals):
    if not intervals:
        return []
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out
""",
    "A7": """
def sum_to_n(n):
    return n * (n + 1) // 2
""",
    "A8": """
def parse_csv(text):
    rows = []
    for line in text.splitlines():
        fields = [f.strip() for f in line.split(',')]
        if len(fields) == 3:
            rows.append(tuple(fields))
    return rows
""",
    "A9": """
import functools


def retry(times):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for _ in range(times):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last = exc
            raise last
        return wrapper
    return deco
""",
    "A10": """
def group_anagrams(words):
    buckets = {}
    for w in words:
        buckets.setdefault(''.join(sorted(w)), []).append(w)
    return list(buckets.values())
""",
    "A11": """
def is_valid_ipv4(s):
    parts = s.split('.')
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit():
            return False
        if len(p) > 1 and p[0] == '0':      # 拒绝前导零
            return False
        if not 0 <= int(p) <= 255:
            return False
    return True
""",
    "A12": """
def rle_encode(s):
    if not s:
        return ''
    out = []
    prev, cnt = s[0], 1
    for ch in s[1:]:
        if ch == prev:
            cnt += 1
        else:
            out.append(f'{prev}{cnt}')
            prev, cnt = ch, 1
    out.append(f'{prev}{cnt}')
    return ''.join(out)
""",
}

# 三语用例 E1-EN / E1-CN / E1-JP 是同一个函数，共用一份参考解
_REVERSE_WORDS = """
def reverse_words(s):
    return ' '.join(s.split()[::-1])
"""
for _cid in ("E1-EN", "E1-CN", "E1-JP"):
    ORACLES[_cid] = _REVERSE_WORDS
