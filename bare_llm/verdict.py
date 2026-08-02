#!/usr/bin/env python3
"""统一判分口径：F2P / P2P 分离 + partial credit。

【本文件与 ~/Documents/dgx/claude-eval/verdict.py 保持同构】——两套评测（裸 LLM / Claude Code 外壳）
共用同一套指标定义，横向对照时刻度才一致。改动请两边同步。

借鉴 DeepSWE（datacurve）的验证器设计，把原来压成一个 bool 的判分拆成两类独立指标：

  F2P (fail-to-pass)  —— 「新需求做到了多少」。基线下必然失败的检查项，模型做对才会转绿。
  P2P (pass-to-pass)  —— 「既有功能有没有被弄坏」。基线下本来就通过的检查项，必须保持绿。

为什么值得拆：2026-08-02 在 DeepSWE 上实测 qwen3.6-35b-a3b，形态是 **P2P 全部满分、F2P 基本归零**
——即「改代码很安全但实现不出新功能」。如果只有一个 bool，这个信息完全看不见，只知道「失败」。
另外三卷对本地这一档模型已接近饱和（35/36、NIAH 24/24），**换更细的刻度就能在饱和区继续区分模型**，
不必非得再出更难的题。

partial 的公式与 DeepSWE 的 `reward.json` 保持一致，便于横向对照：

    partial = (f2p_passed + p2p_passed) / (f2p_total + p2p_total)

`passed`（全或无）保持与历史结果同口径，老数据仍可比。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Verdict:
    """一次判分的结构化结果。

    只关心「过没过」的老代码可以继续用 `bool(verdict)` 或 `.passed`；
    想看细粒度差异就读 `.f2p` / `.p2p` / `.partial`。
    """

    f2p_passed: int = 0
    f2p_total: int = 0
    p2p_passed: int = 0
    p2p_total: int = 0
    detail: str = ""
    # 判分器自己出错时置位（区别于「模型答错」，避免把框架故障记成模型能力）
    grader_error: str = ""

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
        """全或无：F2P 必须全过，且 P2P 一个都不能坏。与历史 bool 口径一致。"""
        if self.grader_error:
            return False
        if self.f2p_total == 0:            # 没有 F2P 项的用例，只要没弄坏东西就算过
            return self.p2p_passed == self.p2p_total
        return self.f2p_passed == self.f2p_total and self.p2p_passed == self.p2p_total

    def __bool__(self) -> bool:
        return self.passed

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "f2p_passed": self.f2p_passed, "f2p_total": self.f2p_total, "f2p": round(self.f2p, 4),
            "p2p_passed": self.p2p_passed, "p2p_total": self.p2p_total, "p2p": round(self.p2p, 4),
            "partial": round(self.partial, 4),
            "detail": self.detail,
            "grader_error": self.grader_error,
        }

    def summary(self) -> str:
        """给终端一行输出用。"""
        s = f"F2P {self.f2p_passed}/{self.f2p_total} P2P {self.p2p_passed}/{self.p2p_total} part={self.partial:.2f}"
        return s + (f" ⚠grader:{self.grader_error}" if self.grader_error else "")


def normalize(raw) -> Verdict:
    """把 grade() 的各种返回形态统一成 Verdict。

    兼容三种写法，便于逐个迁移旧判分函数而不必一次改完：
      - Verdict                      → 原样
      - (bool, str)                  → 折算成单个 F2P 检查项（老口径）
      - bool                         → 同上，detail 为空
    """
    if isinstance(raw, Verdict):
        return raw
    if isinstance(raw, tuple) and len(raw) == 2:
        ok, detail = raw
        v = Verdict(detail=str(detail))
        return v.f2p_add(bool(ok))
    if isinstance(raw, bool):
        return Verdict().f2p_add(raw)
    raise TypeError(f"grade() 返回了无法识别的类型: {type(raw)!r}")
