#!/usr/bin/env python3
"""用例定义与统一判分入口。

**用例形态的总原则（2026-08-02 主人定的方向）**：

> 「实际使用场景基本都是模糊的方向，我只说我想要什么，由模型探索该怎么做；
>   把要求写得非常明确那我自己做就好了，要 Claude Code 干什么？」

所以除了「工具纪律」这一类天生就是短交互的题，其余用例一律：
  - prompt 用**用户口吻**说想要什么，不给函数名/字段名/子命令名/算法；
  - 判分只看**外部可观察行为**（跑起来对不对、老功能有没有坏），不碰内部结构；
  - 验收测试**对模型不可见**（存在保管库里，判分时才临时注入）。

判分口径由基线快照自动划分 F2P/P2P，见 core/baseline.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core import baseline as _baseline
from core import pytest_runner, workspace
from core.judge import Rubric
from core.verdict import Verdict, from_baseline


@dataclass
class Case:
    id: str
    dim: str                       # 维度名，用于报告分组
    suite: str                     # 用例项目模板目录名（suites/<suite>）
    prompt: str                    # 交给模型的自然语言需求（用户口吻）
    k: int = 1                     # 重复次数：方差大的维度要多跑
    hidden: Optional[str] = None   # 保管库里的隐藏验收测试名（core/vault）
    test_targets: Optional[list] = None   # 限定 pytest 目标，默认收集全部
    check: Optional[Callable] = None      # 附加行为检查 fn(ctx) -> Verdict
    oracle: Optional[Callable] = None     # 参考解 fn(work) -> dict | None
    rubric: Optional[Rubric] = None       # 开放题判据（离线 LLM-judge 判）
    drop: Optional[list] = None           # 复制模板后要删掉的路径（开卷/闭卷对照用）
    # 判分前从模板还原的路径：默认把可见测试还原回去，防止「改测试让它变绿」
    restore: Optional[list] = field(default_factory=lambda: ["tests"])
    timeout: int = 600
    notes: str = ""                # 用例意图备忘，只给人看

    @property
    def is_open_ended(self) -> bool:
        return self.rubric is not None


def grade(case: Case, ctx: dict) -> Verdict:
    """统一判分入口。

    顺序：先按基线快照跑验收测试，再叠加用例自己的行为检查。
    **模型中断（超时/空输出）时依然会跑测试** —— 它可能已经改了一半，
    partial 仍有信息量；只是 `aborted` 一旦置位，`passed` 必为 False。
    """
    v = Verdict()
    if case.is_open_ended:
        # 开放题的分数由离线裁判给（run_eval.py --judge），这里只占位并存全文
        v.note("待裁判判分")
        v.aborted = ctx.get("aborted", "")
        return v

    if case.hidden or case.test_targets:
        snap = _baseline.load().get(case.id)
        if not snap:
            return v.fail_grader(f"{case.id} 没有基线快照，先跑 --baseline")
        # 验收标准由评测方说了算：模型对可见测试的改动一律还原后再判
        workspace.restore(ctx["work"], case.suite, case.restore)
        files = _baseline.hidden_files(case)
        with pytest_runner.injected(ctx["work"], files):
            now, detail = pytest_runner.run(ctx["work"], case.test_targets)
        if not now:
            return v.fail_grader(f"跑不出任何测试：{detail}")
        v = from_baseline(snap["tests"], now)
        v.note(detail)

    if case.check:
        v.merge(case.check(ctx))

    if ctx.get("aborted"):
        v.aborted = ctx["aborted"]
    return v


def make_ctx(case: Case, work: Path, run_out: dict) -> dict:
    """给判分函数用的上下文。"""
    ctx = dict(run_out)
    ctx.update(case=case, work=work, suite=case.suite,
               diff=workspace.diff_against_template(work, case.suite, drop=case.drop))
    return ctx


# ---------- 用例清单 ----------
from .tool_discipline import CASES as _TOOL          # noqa: E402
from .fuzzy_feature import CASES as _FUZZY           # noqa: E402
from .symptom_debug import CASES as _DEBUG           # noqa: E402
from .compatibility import CASES as _COMPAT          # noqa: E402
from .multistep import CASES as _MULTI               # noqa: E402
from .constraints import CASES as _CONSTRAINT        # noqa: E402
from .comprehension import CASES as _COMPREHEND      # noqa: E402
from .diagnosis import CASES as _DIAG                # noqa: E402

CASES = (_TOOL + _FUZZY + _DEBUG + _COMPAT + _MULTI + _CONSTRAINT + _COMPREHEND + _DIAG)


def by_id(ids) -> list:
    want = set(ids)
    return [c for c in CASES if c.id in want]
