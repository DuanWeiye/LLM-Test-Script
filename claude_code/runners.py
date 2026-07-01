#!/usr/bin/env python3
"""可插拔的「agent 外壳驱动」—— 把一次 agent 运行统一成同一个接口。

同一批用例、同一套 sandbox 隔离与判分逻辑，只把「用哪个 agent CLI 当外壳」这一层换掉：

  - claude —— Claude Code（`claude -p ... --output-format stream-json`）
  - codex  —— OpenAI Codex CLI（`codex exec --json`）
  - hermes —— Nous Research Hermes Agent（`hermes -z ...`）

每个驱动实现两件事：
  check(model, settings) -> str|None      # 预检配置是否就位；返回错误串或 None
  __call__(...)          -> dict          # 跑一次，返回统一结构

统一返回结构（run_eval.py 与各用例 grade 依赖这些键）：
  result       —— 模型最终文本输出
  tools        —— [{"name","input"}]，本轮调用过的工具
  tools_unknown—— True 表示「工具轨迹没能可靠采集」（该外壳机器可读性不足时置位，
                  提醒依赖工具数的判分项（如 A1）需人工复核，绝不静默当成「没调工具」）
  num_turns    —— 轮数（拿不到则 None）
  usage        —— token 用量 dict
  is_error     —— 外壳自身是否报错/超时
  wall         —— 墙钟耗时（秒）
  stderr       —— stderr 末尾片段
  raw_tail     —— stdout 末尾片段（排障用）

隔离「策略」（整根只读 + 遮蔽评测内部/答案文档 + 暴露 sandbox）由本模块统一提供，
各外壳只额外贡献自己的 home 目录绑定与具体命令行 —— 换外壳不动隔离与判分。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

HOME = Path.home()
DEFAULT_TIMEOUT = 600


# ---------- 共用：bwrap 反作弊隔离前缀 ----------
def _bwrap_base(root: Path, settings: Path, sandbox: Path, answer_docs, expose_md: bool):
    """所有外壳共用的隔离前缀。

    整根只读挂入 → 用 tmpfs 遮蔽评测目录（DESIGN/判分逻辑/答案）→ 再把 settings（只读）
    与 sandbox（读写）重新暴露；闭卷时额外 tmpfs 掉答案文档目录。
    这样无论哪个外壳，模型都无法 grep 到判分脚本或标准答案「开卷作弊」。
    """
    cmd = [
        "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--tmpfs", str(root),
        "--ro-bind", str(settings), str(settings),
        "--bind", str(sandbox), str(sandbox),
    ]
    if not expose_md and answer_docs:
        cmd += ["--tmpfs", str(answer_docs)]
    return cmd


def _timeout_result(timeout: float) -> dict:
    return {"result": "", "tools": [], "tools_unknown": False, "num_turns": None,
            "usage": {}, "is_error": True, "wall": float(timeout),
            "stderr": "TIMEOUT", "raw_tail": ""}


def _run(cmd, cwd, timeout, env=None):
    """跑一条命令，返回 (proc|None, wall)。超时返回 (None, timeout)。"""
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return None, timeout
    return proc, time.time() - t0


class Runner:
    name = "base"

    def check(self, model: str, settings: Path):
        return None

    def __call__(self, model, prompt, cwd, *, root, settings, sandbox,
                 answer_docs, expose_md, timeout=DEFAULT_TIMEOUT) -> dict:
        raise NotImplementedError


# ================= Claude Code =================
class ClaudeRunner(Runner):
    """Claude Code 外壳：`claude -p` + stream-json。每个模型一份 settings/<model>.json。"""
    name = "claude"

    def check(self, model, settings):
        f = settings / f"{model}.json"
        return None if f.exists() else f"缺 settings/{model}.json"

    def __call__(self, model, prompt, cwd, *, root, settings, sandbox,
                 answer_docs, expose_md, timeout=DEFAULT_TIMEOUT):
        claude_cmd = [
            "claude", "-p", prompt,
            "--settings", str(settings / f"{model}.json"),
            "--setting-sources", "project",          # 不加载用户级 ~/.claude/CLAUDE.md
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "bypassPermissions",
        ]
        # claude 的登录态/缓存在 ~/.claude，需读写暴露
        binds = ["--bind", str(HOME / ".claude"), str(HOME / ".claude")]
        cmd = (_bwrap_base(root, settings, sandbox, answer_docs, expose_md)
               + binds + ["--chdir", str(cwd)] + claude_cmd)
        proc, wall = _run(cmd, cwd, timeout)
        if proc is None:
            return _timeout_result(timeout)

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
        return {"result": result_text, "tools": tools, "tools_unknown": False,
                "num_turns": num_turns, "usage": usage, "is_error": is_error,
                "wall": wall, "stderr": proc.stderr[-500:], "raw_tail": proc.stdout[-500:]}


# ================= OpenAI Codex CLI =================
class CodexRunner(Runner):
    """Codex 外壳：`codex exec --json`，输出 JSONL 事件流。

    模型用文档明确的 `-m/--model` 逐次覆盖；供应商走 CODEX_HOME/config.toml 里的默认
    `model_provider`（在示例配置中置为 local）。CODEX_HOME 指向 settings/codex
    （含 config.toml + 会话/日志，需读写）。
    `--dangerously-bypass-approvals-and-sandbox` 关掉 Codex 自带沙箱与批准 —— 隔离交给我们的 bwrap。

    注意：2026-02 起 Codex 仅支持 wire_api="responses"（OpenAI Responses API）。
    本机 llama-swap 只有 chat/completions，须经 LiteLLM 等网关转出 Responses 面，
    并在 config.toml 的 [model_providers.*] 指向该网关。详见根目录 README 的「Part 2」。
    """
    name = "codex"

    def _home(self, settings):
        return settings / "codex"

    def check(self, model, settings):
        cfg = self._home(settings) / "config.toml"
        return None if cfg.exists() else "缺 settings/codex/config.toml（含默认 model_provider + [model_providers.*]）"

    def __call__(self, model, prompt, cwd, *, root, settings, sandbox,
                 answer_docs, expose_md, timeout=DEFAULT_TIMEOUT):
        codex_home = self._home(settings)
        codex_cmd = [
            "codex", "exec", "--json",
            "--skip-git-repo-check",
            "-C", str(cwd),
            "-m", model,                                    # 覆盖模型；供应商用 config.toml 默认
            "--dangerously-bypass-approvals-and-sandbox",   # 关自带沙箱/批准，交给 bwrap
            prompt,
        ]
        # settings 整体是只读绑定，这里把 codex_home 重新绑成可写（后者覆盖前者）
        binds = ["--bind", str(codex_home), str(codex_home)]
        cmd = (_bwrap_base(root, settings, sandbox, answer_docs, expose_md)
               + binds + ["--chdir", str(cwd)] + codex_cmd)
        # CODEX_HOME 指到我们的配置目录；API key 由 config.toml 的 env_key 命名、从父进程环境继承
        env = {**os.environ, "CODEX_HOME": str(codex_home)}
        proc, wall = _run(cmd, cwd, timeout, env=env)
        if proc is None:
            return _timeout_result(timeout)

        tools, result_text, usage, is_error = [], "", {}, False
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            typ = ev.get("type")
            if typ == "item.completed":
                item = ev.get("item", {})
                it = item.get("type")
                if it == "agent_message":
                    result_text = item.get("text", "") or result_text   # 保留最后一条为最终答复
                elif it == "command_execution":
                    tools.append({"name": "shell",
                                  "input": {"command": item.get("command"),
                                            "exit_code": item.get("exit_code")}})
                elif it == "file_change":
                    for ch in item.get("changes", []):
                        tools.append({"name": "file_change", "input": ch})
                elif it == "mcp_tool_call":
                    tools.append({"name": f"mcp:{item.get('server')}/{item.get('tool')}",
                                  "input": item.get("arguments")})
                elif it == "web_search":
                    tools.append({"name": "web_search", "input": {"query": item.get("query")}})
            elif typ == "turn.completed":
                usage = ev.get("usage", {}) or {}
            elif typ in ("turn.failed", "error"):
                is_error = True
        return {"result": result_text, "tools": tools, "tools_unknown": False,
                "num_turns": None, "usage": usage, "is_error": is_error,
                "wall": wall, "stderr": proc.stderr[-500:], "raw_tail": proc.stdout[-800:]}


# ================= Nous Hermes Agent =================
class HermesRunner(Runner):
    """Hermes 外壳：`hermes -z` 出「纯最终文本」，最利于文本类判分。

    Hermes 配置固定读 ~/.hermes/config.yaml（无 --config 旗标），故用 bwrap 把
    settings/hermes 绑到 ~/.hermes 实现「每次评测用我们指定的配置」。模型用 -m 覆盖。
    `--yolo` 免危险命令批准（无人值守）。

    机器可读性弱点：`-z` 只吐最终文本、不含工具轨迹。工具列表尽力经
    `hermes sessions export` 从最近会话补采（JSONL）；采不到则 tools_unknown=True，
    交由 run_eval 标注、避免把「未采集」误当成「没调工具」（影响 A1 等）。
    """
    name = "hermes"

    def _home(self, settings):
        return settings / "hermes"

    def check(self, model, settings):
        cfg = self._home(settings) / "config.yaml"
        return None if cfg.exists() else "缺 settings/hermes/config.yaml（模型/供应商/base_url 配置）"

    def _bwrap(self, root, settings, sandbox, answer_docs, expose_md, cwd, hermes_home, argv):
        # 把 settings/hermes 绑成 ~/.hermes（覆盖只读根），Hermes 会话/缓存写在此处
        binds = ["--bind", str(hermes_home), str(HOME / ".hermes")]
        return (_bwrap_base(root, settings, sandbox, answer_docs, expose_md)
                + binds + ["--chdir", str(cwd)] + argv)

    def __call__(self, model, prompt, cwd, *, root, settings, sandbox,
                 answer_docs, expose_md, timeout=DEFAULT_TIMEOUT):
        hermes_home = self._home(settings)

        run_cmd = ["hermes", "-z", prompt, "--yolo"]
        if model:
            run_cmd += ["-m", model]                        # 形如 provider/model
        cmd = self._bwrap(root, settings, sandbox, answer_docs, expose_md, cwd, hermes_home, run_cmd)
        proc, wall = _run(cmd, cwd, timeout)
        if proc is None:
            return _timeout_result(timeout)

        result_text = (proc.stdout or "").strip()
        is_error = proc.returncode != 0

        # 尽力补采工具轨迹：把最近会话导出为 JSONL 到 host 可见路径（hermes_home 内），再解析
        tools, tools_unknown = self._collect_tools(
            root, settings, sandbox, answer_docs, expose_md, cwd, hermes_home)

        return {"result": result_text, "tools": tools, "tools_unknown": tools_unknown,
                "num_turns": None, "usage": {}, "is_error": is_error,
                "wall": wall, "stderr": proc.stderr[-500:], "raw_tail": proc.stdout[-800:]}

    def _collect_tools(self, root, settings, sandbox, answer_docs, expose_md, cwd, hermes_home):
        """`hermes sessions export` 导出最近会话为 JSONL，防御式解析工具调用名。

        Hermes 会话 JSONL 的确切字段需实机核实；这里对多种可能形状都做兜底：
        role=='tool' / type 含 'tool' / 含 tool_calls[] / 含 tool_name。
        导出失败或空 → (tools=[], tools_unknown=True)。
        """
        export_path = hermes_home / "_last_export.jsonl"
        try:
            if export_path.exists():
                export_path.unlink()
        except Exception:
            pass
        exp_cmd = ["hermes", "sessions", "export", str(HOME / ".hermes" / "_last_export.jsonl")]
        cmd = self._bwrap(root, settings, sandbox, answer_docs, expose_md, cwd, hermes_home, exp_cmd)
        proc, _ = _run(cmd, cwd, 120)
        if proc is None or not export_path.exists():
            return [], True

        tools, saw_any = [], False
        try:
            for line in export_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                saw_any = True
                # 形状 1：明确的工具消息
                if obj.get("role") == "tool" or "tool" in str(obj.get("type", "")).lower():
                    name = obj.get("tool_name") or obj.get("name") or "tool"
                    tools.append({"name": name, "input": obj.get("arguments") or obj.get("input") or {}})
                # 形状 2：assistant 消息内嵌 tool_calls[]
                for tc in obj.get("tool_calls", []) or []:
                    fn = (tc.get("function") or {})
                    tools.append({"name": fn.get("name") or tc.get("name") or "tool",
                                  "input": fn.get("arguments") or {}})
        except Exception:
            return [], True
        # 导出成功但一条都没解析出 → 视为「格式未知」，别误当没调工具
        return (tools, False) if saw_any else ([], True)


RUNNERS = {r.name: r for r in (ClaudeRunner(), CodexRunner(), HermesRunner())}
