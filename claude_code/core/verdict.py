#!/usr/bin/env python3
"""统一判分口径：F2P / P2P 分离 + partial credit。

  F2P (fail-to-pass)  —— 「新需求做到了多少」。基线下必然失败的检查项，模型做对才转绿。
  P2P (pass-to-pass)  —— 「既有功能有没有被弄坏」。基线下本来就通过的检查项，必须保持绿。

为什么值得拆：只有一个 bool 时，「什么都没做」和「做了一半但没弄坏东西」不可区分；
实测本机模型的典型形态恰恰是 P2P 满分、F2P 偏低（改代码很安全但实现不出新功能）。

partial 的公式：

    partial = (f2p_passed + p2p_passed) / (f2p_total + p2p_total)

**F2P/P2P 的归属不再由人手写**，而是由基线快照自动决定（见 core/baseline.py）：
在干净项目上跑一遍全部检查项，基线红的自动算 F2P、基线绿的自动算 P2P。
手工维护测试名单曾经反复出错（列错一条，P2P 就永远不可能满分）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Verdict:
    """一次判分的结构化结果。"""

    f2p_passed: int = 0
    f2p_total: int = 0
    p2p_passed: int = 0
    p2p_total: int = 0
    detail: str = ""
    # 判分器自身出错（拷不进测试、pytest 收集失败…）时置位。
    # 与「模型答错」严格区分：框架故障不该记到模型头上。
    grader_error: str = ""
    # 模型侧的异常终止：超时 / CLI 报错。同样不是「答错」，但确实没交付，计 0 分。
    aborted: str = ""

    # ---------- 构造辅助 ----------
    def f2p_add(self, ok: bool, n: int = 1) -> "Verdict":
        """记入 n 个新需求检查项，ok=True 表示全部通过。"""
        self.f2p_total += n
        if ok:
            self.f2p_passed += n
        return self

    def p2p_add(self, ok: bool, n: int = 1) -> "Verdict":
        """记入 n 个既有功能检查项。"""
        self.p2p_total += n
        if ok:
            self.p2p_passed += n
        return self

    def note(self, s: str) -> "Verdict":
        self.detail = (self.detail + " " + s).strip() if self.detail else s
        return self

    def fail_grader(self, msg: str) -> "Verdict":
        self.grader_error = msg[:200]
        return self

    # ---------- 派生指标 ----------
    @property
    def f2p(self) -> float:
        return self.f2p_passed / self.f2p_total if self.f2p_total else 0.0

    @property
    def p2p(self) -> float:
        # 没有 P2P 检查项时视为满分（纯问答题不存在「弄坏既有功能」）
        return self.p2p_passed / self.p2p_total if self.p2p_total else 1.0

    @property
    def partial(self) -> float:
        tot = self.f2p_total + self.p2p_total
        return (self.f2p_passed + self.p2p_passed) / tot if tot else 0.0

    @property
    def passed(self) -> bool:
        """全或无：F2P 必须全过，且 P2P 一个都不能坏。"""
        if self.grader_error or self.aborted:
            return False
        if self.f2p_total == 0:            # 没有 F2P 项的用例，只要没弄坏东西就算过
            return self.p2p_total > 0 and self.p2p_passed == self.p2p_total
        return self.f2p_passed == self.f2p_total and self.p2p_passed == self.p2p_total

    def __bool__(self) -> bool:
        return self.passed

    def merge(self, other: "Verdict") -> "Verdict":
        """把另一份判分并进来（测试类判分 + 附加的行为检查）。"""
        self.f2p_passed += other.f2p_passed
        self.f2p_total += other.f2p_total
        self.p2p_passed += other.p2p_passed
        self.p2p_total += other.p2p_total
        if other.detail:
            self.note(other.detail)
        if other.grader_error and not self.grader_error:
            self.grader_error = other.grader_error
        if other.aborted and not self.aborted:
            self.aborted = other.aborted
        return self

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "f2p_passed": self.f2p_passed, "f2p_total": self.f2p_total, "f2p": round(self.f2p, 4),
            "p2p_passed": self.p2p_passed, "p2p_total": self.p2p_total, "p2p": round(self.p2p, 4),
            "partial": round(self.partial, 4),
            "detail": self.detail,
            "grader_error": self.grader_error,
            "aborted": self.aborted,
        }

    def summary(self) -> str:
        """给终端一行输出用。"""
        s = f"F2P {self.f2p_passed}/{self.f2p_total} P2P {self.p2p_passed}/{self.p2p_total} part={self.partial:.2f}"
        if self.aborted:
            s += f" ⚠中断:{self.aborted}"
        if self.grader_error:
            s += f" ⚠判分器:{self.grader_error[:60]}"
        return s


def from_baseline(baseline: dict, now: dict) -> Verdict:
    """按基线快照把「本次测试结果」自动分成 F2P / P2P 两类。

    baseline / now 都是 {node_id: bool}。
      - 基线 False（本来就红）→ F2P：这是本用例要求做到的新行为
      - 基线 True （本来就绿）→ P2P：这是不许弄坏的既有行为
    基线里没有、本次新出现的 node_id（模型自己加的测试）一律忽略 —— 判分只认验收侧的检查项。
    """
    v = Verdict()
    missing = []
    for node, base_ok in baseline.items():
        if node not in now:
            missing.append(node)
            continue
        if base_ok:
            v.p2p_add(bool(now[node]))
        else:
            v.f2p_add(bool(now[node]))
    if missing:
        # 检查项消失＝模型把测试文件删了/改坏了导致收集不到，按未通过计，并在 detail 里点名
        for node in missing:
            if baseline[node]:
                v.p2p_add(False)
            else:
                v.f2p_add(False)
        v.note(f"缺失{len(missing)}项(测试未被收集)")
    return v
