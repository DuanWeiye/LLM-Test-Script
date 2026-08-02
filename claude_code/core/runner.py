#!/usr/bin/env python3
"""跑一次 Claude Code：同一个外壳，只换底层模型 endpoint。

**不再使用 bwrap**。原先靠 mount namespace 把评测目录遮空防泄题，代价是每次评测都要
`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`。现在换成三层零特权隔离：

  1. 工作目录是 /tmp 下的中性随机目录，与评测框架无路径关联（core/workspace.py）
  2. 验收测试压缩存放在保管库，模型运行阶段根本不在磁盘上（core/vault.py）
  3. `--setting-sources project` + settings 里的 deny 规则，挡住用户级 CLAUDE.md
     与会话记录目录 —— 前者曾经真的泄过题（全局 CLAUDE.md 里就写着某道诊断题的答案）
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings"


def settings_path(model: str) -> Path:
    return SETTINGS / f"{model}.json"


def run_claude(model: str, prompt: str, cwd: Path, timeout: int = 600) -> dict:
    """跑一次 `claude -p`，解析 stream-json 拿工具调用与最终输出。"""
    cmd = [
        "claude", "-p", prompt,
        "--settings", str(settings_path(model)),
        "--setting-sources", "project",     # 不加载用户级 ~/.claude/CLAUDE.md（防泄题）
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"result": "", "tools": [], "num_turns": None, "usage": {},
                "aborted": f"超时{timeout}s", "wall": float(timeout), "stderr": "", "raw_tail": ""}

    tools, result_text, num_turns, usage, is_error = [], "", None, {}, False
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "tool_use":
                    tools.append({"name": blk.get("name"), "input": blk.get("input", {})})
        elif t == "result":
            result_text = ev.get("result", "") or ""
            num_turns = ev.get("num_turns")
            usage = ev.get("usage", {})
            is_error = ev.get("is_error", False)

    aborted = ""
    if is_error:
        aborted = "CLI报错"
    elif not result_text.strip() and not tools:
        # 空输出且一个工具都没调 —— 历史上出现过（模型思考跑飞、endpoint 挂掉），
        # 这不是「答错」，单独标记出来才不会污染能力结论
        aborted = "空输出"
    return {"result": result_text, "tools": tools, "num_turns": num_turns, "usage": usage,
            "aborted": aborted, "wall": time.time() - t0,
            "stderr": proc.stderr[-500:], "raw_tail": proc.stdout[-500:]}


def tool_names(ctx: dict) -> list:
    return [t["name"] for t in ctx.get("tools", [])]


def tool_inputs(ctx: dict, name: str) -> list:
    """取某个工具的全部调用参数，判分时用得上（例如「有没有真的调 Write 落盘」）。"""
    return [t.get("input", {}) for t in ctx.get("tools", []) if t.get("name") == name]
