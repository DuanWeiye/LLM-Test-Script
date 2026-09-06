#!/usr/bin/env python3
"""跑一次 opencode：同一个外壳，只换底层模型 endpoint。

**2026-09-06 从 Claude Code 换成 opencode**。换壳的动机是降低「模型针对某个外壳做过专门
优化」对结论的污染 —— Tiel-Coder(Ornith 微调) 那次的归因就是「朝 agentic harness 收敛」，
froggeric 模板在 27B 上净扣 4~7 分、在 35B 上反而 +10，外壳/模板耦合已经不止一次动摇过结论。

顺带消掉一层失真：CC 只认 Anthropic 协议，本机模型得经 LiteLLM(127.0.0.1:1235) 转一道；
opencode 原生吃 OpenAI 兼容端点，**直连 llama-swap 12345**，工具调用不再过翻译层。

判分侧零改动 —— `cases/` 只看 `len(ctx["tools"])`、`ctx["result"]` 和文件树 diff，
从不认工具名，所以本模块只要维持返回 dict 的形状（result/tools/num_turns/usage/
aborted/wall/stderr/raw_tail）就够了。

## 防泄题（这套评测踩过的最贵的坑）

opencode 的规则文件加载比 CC 更激进，2026-09-06 逐条实测过三条通道：

  1. 全局 `~/.config/opencode/AGENTS.md`  → `OPENCODE_CONFIG_DIR` 指向干净目录挡住
  2. **`~/.claude/CLAUDE.md`**（CC 兼容 fallback，当年真的泄过题的那个文件）
     → `OPENCODE_DISABLE_CLAUDE_CODE=1` 挡住。实测不加这个，模型会直接答出
       「根据 CLAUDE.md 中的信息……」
  3. **向上遍历父目录的 AGENTS.md** → **挡不住**。opencode 是把祖先目录的规则文件
     全部收集起来拼接，不是就近优先：在工作目录里放一份自己的 AGENTS.md 想截断，
     父目录那份照样被读进去（实测）。

第 3 条只能靠环境保证。工作目录在 `/tmp/wk-xxx/<项目名>` 下，而 `/tmp` 是任何进程
都能写的公共目录 —— 一旦那里有 AGENTS.md，评测就被静默污染，且事后极难发现
（上次泄题就是过了很久才发现的）。所以 `_assert_clean_ancestry()` 在每次运行前扫父链，
**发现规则文件就直接报错中止，而不是继续跑**：宁可停下来，也不要产出一份不知道
被污染过的成绩单。

## ★★ 2026-09-06 事故：模型跑出了工作目录，在真仓库里干活

第一轮正式评测（qwen3.6-35b-a3b，79 次运行）**全程不在 /tmp 工作目录里**，而是在
`~/Documents/LLM-Test-Script/agent` 里跑的。后果：读了 `CASEBOOK.md`（写着全部答案）、
`cases/*.py` 出题源，`python3 -m core.vault dump R3` 打出了隐藏验收测试，改了题目模板，
还在真仓库里 `git commit` 两次 + `git reset --hard HEAD~1`，把上个会话未提交的换壳改动
全部冲掉、删光了 `results/` 里的历史成绩。那一轮成绩已作废。

**根因**：`subprocess(cwd=...)` 对 opencode 无效。opencode 是从 `OPENCODE_CONFIG` /
`OPENCODE_CONFIG_DIR` 的所在位置向上找 git 仓库来定 project 与工作目录的 ——
配置当时放在 `<repo>/agent/settings/*.json` 与 `<repo>/agent/oc_home/`，于是它认定
「项目＝本仓库」。证据：`~/.local/share/opencode/opencode.db` 里 108 个评测 session 的
`directory` 全是 `<repo>/agent`，而上个会话手工探针那 7 个（配置放在 /tmp 的 scratchpad）
是对的 —— 同一份代码，只因配置位置不同，工作目录就完全不同。

**三层加固**（缺一层都不够，按「配置位置 → 沙箱 → 事后核对」纵深排列）：

  1. `_isolated_oc_env()`：每次运行现造一套 **完全在 /tmp、且不在任何 git 仓库里** 的
     opencode 配置目录（config / config_dir / XDG data / cache 全在里面），
     跑完即删。仓库里不再有任何 opencode 认得的东西。
  2. `_sandbox_prefix()`：用 **bwrap** 把整个文件系统只读挂载，只有本次工作目录与
     那套临时配置目录可写。就算模型想写仓库，内核层面写不动。
     bwrap 不可用时**不静默降级**——`EVAL_REQUIRE_SANDBOX=0` 才允许裸跑。
  3. `_framework_fingerprint()`：每次运行前后对框架树（agent/、bare_llm/、
     make_report.py、.git 的 HEAD/index/refs）做内容指纹，**一旦对不上立即抛错中止整轮**。
     这次是两小时后靠人眼发现的，不能再指望人眼。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings"
# ⚠ 曾经这里是 `OC_HOME = ROOT / "oc_home"`（仓库内的空目录）——**正是它把模型引进了仓库**：
#   opencode 从配置目录向上找 git 仓库当 project。现在配置目录改为每次运行现造在 /tmp，
#   见 `_isolated_oc_env()`。仓库内不再保留任何 opencode 配置目录。
# opencode 二进制装在项目内 vendor/（npm 的 arm64 包），不依赖全局安装，
# 换机器只要 `cd vendor && npm install` 就能复现同一版本。
OC_BIN = ROOT.parent / "vendor" / "node_modules" / ".bin" / "opencode"

# 各用例的 timeout 是按本机主力模型（~70 tok/s、不开思考）的实测耗时定的。
# 换成慢很多的模型（稠密模型、开思考的 reasoning 模型）时，同样的能力会因为墙钟变长
# 而撞上固定超时，结果被记成「中断」——那是环境问题，不是模型答错，会污染能力结论。
# 用倍数放大而不是逐个用例改死数字：默认 1 时行为与历史完全一致，跑慢模型时整体放大一次。
#
# ⚠ 这些数字是按 Claude Code 标定的，opencode 的每轮开销未必一样，
#   换壳后第一轮正式评测要复核「中断」的比例，必要时重新标定而不是无脑放大倍数。
_TIMEOUT_MULT = float(os.environ.get("EVAL_AGENT_TIMEOUT_MULT", "1"))

# opencode 会把祖先目录里的这些文件当规则加载 —— 父链上出现任何一个都算泄题风险
_RULE_FILES = ("AGENTS.md", "CLAUDE.md", "opencode.json", "opencode.jsonc")


def settings_path(model: str) -> Path:
    """每个模型一份 opencode 配置（provider baseURL / 模型 id / 采样等）。

    文件本身就是合法的 opencode 配置，直接经 `OPENCODE_CONFIG` 传给它，
    不再像 CC 那样只是一包环境变量。settings/ 已被 .gitignore 忽略，key 不入库。
    """
    return SETTINGS / f"{model}.json"


def _assert_clean_ancestry(cwd: Path) -> None:
    """扫工作目录的父链，发现规则文件就中止。

    只扫父链、不扫工作目录本身 —— 工作目录里的文件是题目的一部分，
    模板里真要放 CLAUDE.md 那也是出题人故意的。
    """
    dirty = []
    for parent in Path(cwd).resolve().parents:
        for name in _RULE_FILES:
            if (parent / name).exists():
                dirty.append(str(parent / name))
    if dirty:
        raise RuntimeError(
            "工作目录的父链上有 opencode 会自动加载的规则文件，评测会被静默污染：\n  "
            + "\n  ".join(dirty)
            + "\n请先移走这些文件再跑评测（opencode 会收集全部祖先目录的规则并拼接，"
              "在工作目录里放一份自己的 AGENTS.md 是挡不住的）。"
        )


class _isolated_oc_env:
    """给一次运行现造一套 opencode 配置/数据目录，**全在 /tmp、且不在任何 git 仓库里**。

    这是 2026-09-06 事故的正面修复（详见模块 docstring）：opencode 不认
    `subprocess(cwd=...)`，它按配置文件的位置向上找 git 仓库来定工作目录。
    只要配置还留在仓库里，模型就会在仓库里干活 —— 所以配置必须离开仓库。

    目录形如 `/tmp/oceval-<随机>/`：
        opencode.json   ← 从 settings/<model>.json 原样拷进来（内容不改，口径不变）
        config_dir/     ← OPENCODE_CONFIG_DIR，保持空，挡开全局 ~/.config/opencode
        data/ cache/ state/  ← XDG 三件套改指到这里，opencode 的 DB/快照都落在临时目录，
                              既不污染用户的 ~/.local/share/opencode，也不给它可写的仓库路径
    用完整个删掉。
    """

    def __init__(self, model: str):
        self.model = model
        self.base = None

    def __enter__(self):
        src = settings_path(self.model)
        if not src.exists():
            raise RuntimeError(f"缺 settings/{self.model}.json")
        self.base = Path(tempfile.mkdtemp(prefix="oceval-", dir="/tmp"))
        shutil.copy2(src, self.base / "opencode.json")
        for sub in ("config_dir", "data", "cache", "state", "home"):
            (self.base / sub).mkdir()
        return self.base

    def __exit__(self, *exc):
        if self.base:
            shutil.rmtree(self.base, ignore_errors=True)
        return False


def _env(model: str, ocdir: Path, cwd: Path) -> dict:
    """构造隔离环境。防泄题三件套 + opencode 的家挪到临时目录 + **把 PWD 摆正**。"""
    env = dict(os.environ)
    # ★★ 2026-09-06 事故的真正根因就在这一行。
    #   `subprocess.run(cwd=...)` 改的是进程的**真 cwd**，但**不动 `PWD` 环境变量** ——
    #   子进程继承的 PWD 还是父进程（run_eval.py，从 <repo>/agent 启动）的那个。
    #   opencode 取工作目录用的是 PWD，于是 25 条用例全部在 <repo>/agent 里执行：
    #   读答案册、改题目模板、往真仓库 git commit，全从这里来。
    #   证据：事故那 108 个 session 的 directory 都是 <repo>/agent，与 run_eval.py 的启动目录
    #   逐字相同；而上个会话手工探针是 `cd <工作目录> && opencode ...`（PWD 正确）→ 目录正确。
    env["PWD"] = str(cwd)
    env.pop("OLDPWD", None)
    env["OPENCODE_CONFIG"] = str(ocdir / "opencode.json")
    env["OPENCODE_CONFIG_DIR"] = str(ocdir / "config_dir")   # 挡开全局 ~/.config/opencode/AGENTS.md
    env["OPENCODE_DISABLE_CLAUDE_CODE"] = "1"                # 挡开 ~/.claude/CLAUDE.md（实测确认有效）
    # XDG 三件套：opencode 的 DB / 快照 / 缓存全部落在临时目录里。
    # 不这么做的话它会写 ~/.local/share/opencode（沙箱里是只读的，会直接起不来），
    # 而且历史 session 会跨用例互相看见。
    env["XDG_CONFIG_HOME"] = str(ocdir / "config_dir")
    env["XDG_DATA_HOME"] = str(ocdir / "data")
    env["XDG_CACHE_HOME"] = str(ocdir / "cache")
    env["XDG_STATE_HOME"] = str(ocdir / "state")
    # 评测跑的是本机模型，不需要也不该有任何云端凭据在环境里
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        env.pop(k, None)
    return env


# ── 第二层：写屏障 ────────────────────────────────────────────────────────
# 两种实现，能力差一个量级，所以**必须让人知道当前在用哪一种**（绝不静默降级）：
#
#   bwrap  内核级：整个文件系统只读挂载，只有工作目录与本次临时配置目录可写。
#          模型就算 `cd <repo> && git commit` 也写不动。**这是想要的那种**。
#          前提：能创建非特权 user namespace。Ubuntu 24.04 起默认被 AppArmor 拦
#          （`kernel.apparmor_restrict_unprivileged_userns=1`），要一次 sudo 才能放开：
#             方案A（针对性，推荐）：给 /usr/bin/bwrap 装一条允许 userns 的 AppArmor profile
#             方案B（一刀切）：sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
#   chmod  同用户级：跑之前把框架树摘掉写权限，跑完恢复。挡得住「顺手改/顺手提交」
#          （git 会直接报 Permission denied），但**挡不住存心 chmod 回来的模型** ——
#          同一个 UID 本来就有这个权限。免 sudo，作为兜底。
#
# 选择：EVAL_SANDBOX=auto(默认，bwrap 可用就用，否则 chmod) | bwrap | chmod | none
_BWRAP = shutil.which("bwrap")
_SANDBOX_MODE = os.environ.get("EVAL_SANDBOX", "auto")


def _bwrap_works() -> bool:
    """真跑一次再说 —— 装了 bwrap ≠ 能用（AppArmor 那道拦在 exec 之后才报错）。"""
    if not _BWRAP:
        return False
    try:
        r = subprocess.run([_BWRAP, "--ro-bind", "/", "/", "true"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


_ACTIVE_SANDBOX = None          # 首次运行时定下来，并打印一次，免得跑完才发现没护栏


def _pick_sandbox() -> str:
    global _ACTIVE_SANDBOX
    if _ACTIVE_SANDBOX:
        return _ACTIVE_SANDBOX
    mode = _SANDBOX_MODE
    if mode == "auto":
        mode = "bwrap" if _bwrap_works() else "chmod"
    if mode == "bwrap" and not _bwrap_works():
        raise RuntimeError("EVAL_SANDBOX=bwrap 但 bwrap 跑不起来（多半是 AppArmor 拦了非特权 "
                           "user namespace）。放开它，或改用 EVAL_SANDBOX=chmod。")
    if mode not in ("bwrap", "chmod", "none"):
        raise RuntimeError(f"EVAL_SANDBOX 取值非法：{mode}")
    _ACTIVE_SANDBOX = mode
    note = {"bwrap": "内核级只读挂载（最强）",
            "chmod": "同用户级只读（免 sudo 兜底；挡不住存心 chmod 回来的模型）",
            "none":  "★ 无写屏障 —— 只剩事后指纹核对，出事只能作废重跑"}[mode]
    print(f"[隔离] 写屏障 = {mode}：{note}", flush=True)
    return mode


def _sandbox_prefix(work: Path, ocdir: Path) -> list:
    """bwrap 模式下的命令前缀；其它模式返回空列表（由 _readonly_framework 兜底）。"""
    if _pick_sandbox() != "bwrap":
        return []
    repo = ROOT.parent
    vendor = OC_BIN.parents[2]                 # <repo>/vendor：opencode 二进制在这儿，必须留着
    return [
        _BWRAP,
        "--die-with-parent",          # 父进程没了就一起死，不留孤儿
        "--ro-bind", "/", "/",        # 整个文件系统只读
        "--dev-bind", "/dev", "/dev",
        "--proc", "/proc",
        # ★ 仓库整个用空 tmpfs 盖住：不只是写不了，是**看都看不到** ——
        #   答案册 CASEBOOK.md、出题源 cases/、隐藏验收测试 vault/ 全部消失。
        #   2026-09-06 事故里模型是真的把 CASEBOOK.md 读出来了，只挡写不够。
        "--tmpfs", str(repo),
        "--ro-bind", str(vendor), str(vendor),  # 盖完再把二进制挂回来（只读）
        "--bind", str(work), str(work),         # 只有这两处可写
        "--bind", str(ocdir), str(ocdir),
        "--",
    ]


# 只要被测模型读到就等于作废的东西。chmod 模式下运行期间连读权限一起摘掉。
# （bwrap 模式不需要这份清单：整个仓库被 tmpfs 盖掉了。）
_ANSWER_KEYS = ("CASEBOOK.md", "CASEBOOK.casebook",
                "agent/cases", "agent/vault", "agent/baseline.json",
                "bare_llm/cases_hard.py", "bare_llm/cases_multi.py",
                "bare_llm/cases_longctx.py", "bare_llm/cases_conflict.py",
                "bare_llm/full_eval.py", "bare_llm/full_eval_hard.py", "bare_llm/oracles.py")


class _readonly_framework:
    """chmod 模式的写屏障：运行期间把框架树摘掉写位，结束后原样恢复。

    只在 EVAL_SANDBOX=chmod 时生效（bwrap 模式下多此一举）。
    目录也要摘写位 —— 否则文件删得掉、也能新建，`git checkout`/`git reset` 照样能改树。
    结果目录 results/ 不动：本进程跑完要往里写。
    """

    def __init__(self):
        self.saved = []

    def __enter__(self):
        if _pick_sandbox() != "chmod":
            return self
        # 整个仓库都摘写位，不挑食 —— 第一版只护了 agent/ 与 bare_llm/，
        # 实测模型直接去改仓库根目录的 README.md 就绕过去了（2026-09-06 加固自测抓到）。
        repo = ROOT.parent
        files = []
        for dirpath, dirnames, filenames in os.walk(repo):
            dirnames[:] = [d for d in dirnames
                           if d not in ("results", "__pycache__", ".pytest_cache", "runs")]
            for name in filenames + dirnames:
                files.append(Path(dirpath, name))
        files.append(repo)
        for f in files:
            try:
                mode = f.stat().st_mode
                self.saved.append((f, mode))
                os.chmod(f, mode & ~0o222)          # 摘写位
            except OSError:
                pass
        # 答案册这一档连读位也摘掉（同一个 UID 也 open 不了，只有 root 能绕过）
        for rel in _ANSWER_KEYS:
            f = repo / rel
            if not f.exists():
                continue
            targets2 = [f] if f.is_file() else [f] + [Path(dp, n)
                                                     for dp, dn, fn in os.walk(f) for n in fn + dn]
            for g in targets2:
                try:
                    mode = g.stat().st_mode
                    self.saved.append((g, mode))
                    os.chmod(g, mode & ~0o777)
                except OSError:
                    pass
        return self

    def __exit__(self, *exc):
        for f, mode in reversed(self.saved):
            try:
                os.chmod(f, mode)
            except OSError:
                pass
        return False


# ── 第三层：框架指纹（事后核对，跑出去了立刻知道）────────────────────────────
_FP_SKIP_DIRS = {"__pycache__", ".pytest_cache", "results", "node_modules", "vendor", "runs"}


def _framework_fingerprint() -> dict:
    """对框架树做内容指纹：路径 → sha256。

    覆盖 agent/（用例、判分器、保管库、模板）、bare_llm/、make_report.py，
    外加 .git 的 HEAD / index / refs —— 事故里模型是**用 git 提交 + reset** 改的仓库，
    只比对工作树文件会漏掉那一类。
    """
    repo = ROOT.parent
    targets = [ROOT, repo / "bare_llm", repo / "make_report.py",
               repo / ".git" / "HEAD", repo / ".git" / "index", repo / ".git" / "refs"]
    out = {}
    for target in targets:
        if target.is_file():
            out[str(target.relative_to(repo))] = hashlib.sha256(target.read_bytes()).hexdigest()
            continue
        if not target.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in _FP_SKIP_DIRS]
            for fn in filenames:
                f = Path(dirpath, fn)
                try:
                    out[str(f.relative_to(repo))] = hashlib.sha256(f.read_bytes()).hexdigest()
                except OSError:
                    pass
    return out


def _assert_framework_intact(before: dict, after: dict) -> None:
    """框架树被动过就中止整轮 —— 只要动过，这一轮的成绩就已经不可信了。"""
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        raise RuntimeError(
            "★ 被测模型改动了评测框架本身（它跑出了工作目录），本轮成绩作废、立即中止：\n  "
            + "\n  ".join(changed[:20])
            + (f"\n  …共 {len(changed)} 处" if len(changed) > 20 else "")
            + "\n先查 core/runner.py 的隔离三层是不是哪层失效了，再重跑。")


def _parse_events(stdout: str) -> dict:
    """解析 `--format json` 的 JSONL 事件流。

    事件形态（2026-09-06 实测 opencode 1.18.29）：
      step_start                       每轮一个，用来数 num_turns
      tool_use    part.tool / part.state.input / part.state.status
      text        part.text            模型说的话，最后一个即最终回答
      step_finish part.tokens          **该步的**用量，不是累计值
    """
    tools, texts, steps = [], [], 0
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "reasoning_tokens": 0}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t, part = ev.get("type"), ev.get("part") or {}
        if t == "step_start":
            steps += 1
        elif t == "tool_use":
            # 被拒绝/出错的调用也照记：工具纪律题考的是「有没有伸手」，
            # 不是「伸手成功没有」，所以不按 status 过滤。
            state = part.get("state") or {}
            tools.append({"name": part.get("tool"),
                          "input": state.get("input", {}) or {},
                          "status": state.get("status")})
        elif t == "text":
            txt = part.get("text") or ""
            if txt.strip():
                texts.append(txt)
        elif t == "step_finish":
            # ⚠ opencode 按步给量且 input 是增量（第二步 input=81 而 cache.read=10156），
            #   CC 是在 result 里一次性给总量。这里逐步累加成 CC 的口径，
            #   不然 token 统计会静默算错 —— 而 usage 正是分辨
            #   「想得多」和「想得少但答对了」的唯一依据。
            tk = part.get("tokens") or {}
            cache = tk.get("cache") or {}
            usage["input_tokens"] += int(tk.get("input") or 0)
            usage["output_tokens"] += int(tk.get("output") or 0)
            usage["reasoning_tokens"] += int(tk.get("reasoning") or 0)
            usage["cache_read_input_tokens"] += int(cache.get("read") or 0)
            usage["cache_creation_input_tokens"] += int(cache.get("write") or 0)
    return {"tools": tools, "result": texts[-1] if texts else "",
            "num_turns": steps or None, "usage": usage}


def run_agent(model: str, prompt: str, cwd: Path,
              timeout: int = 600, effort: str | None = None) -> dict:
    """跑一次 `opencode run`，解析事件流拿工具调用与最终输出。

    `effort` 走 opencode 的 `--variant`（provider-specific reasoning effort，
    如 high/max/minimal）—— 这是 CC `--effort` 的对应物。端点未必认：
    本机 llama-swap 的思考档位是在服务端配的，传了不一定有可观测差异，
    所以对照实验前务必先确认这一档真的传下去了，别拿没生效的旋钮下结论。
    """
    _assert_clean_ancestry(cwd)
    if not OC_BIN.exists():
        raise RuntimeError(f"没找到 opencode 二进制：{OC_BIN}\n"
                           f"请先 `cd {OC_BIN.parents[2]} && npm install opencode-ai@latest`")

    timeout = int(timeout * _TIMEOUT_MULT)
    # 第三层：跑之前先记框架指纹，跑完立刻核对（见 _assert_framework_intact）
    fp_before = _framework_fingerprint()

    with _isolated_oc_env(model) as ocdir, _readonly_framework():   # 第一层＋第二层
        cmd = _sandbox_prefix(cwd, ocdir) + [       # bwrap 可用时再加一道内核级只读
            str(OC_BIN), "run", prompt,
            "--pure",                       # 不加载任何外部插件
            "--auto",                       # 自动批准权限，等价于 CC 的 bypassPermissions
            "--format", "json",
            "-m", f"local/{model}",         # provider 名固定为 local，见 settings/*.json
        ]
        if effort:
            cmd += ["--variant", effort]

        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                                  timeout=timeout, env=_env(model, ocdir, cwd))
        except subprocess.TimeoutExpired:
            timed_out = True

    # ⚠ 指纹必须在 with 之外核对：屏障还开着的时候框架文件是读不到的，
    #   在里面算指纹会把「被我自己摘了权限」误报成「被模型改了」。
    _assert_framework_intact(fp_before, _framework_fingerprint())
    if timed_out:
        return {"result": "", "tools": [], "num_turns": None, "usage": {},
                "aborted": f"超时{timeout}s", "wall": float(timeout), "stderr": "", "raw_tail": ""}
    parsed = _parse_events(proc.stdout)

    aborted = ""
    if proc.returncode != 0:
        aborted = f"CLI报错(exit={proc.returncode})"
    elif not parsed["result"].strip() and not parsed["tools"]:
        # 空输出且一个工具都没调 —— 历史上出现过（模型思考跑飞、endpoint 挂掉），
        # 这不是「答错」，单独标记出来才不会污染能力结论
        aborted = "空输出"
    return {**parsed, "aborted": aborted, "wall": time.time() - t0,
            "stderr": proc.stderr[-500:], "raw_tail": proc.stdout[-500:]}


# 换壳期间保留旧名字，免得漏改哪个调用点就静默走不到新实现
run_claude = run_agent


def tool_names(ctx: dict) -> list:
    return [t["name"] for t in ctx.get("tools", [])]


def token_usage(ctx: dict) -> dict:
    """取本次运行的 token 计数，落盘用。

    没有它就无法分辨「模型想得多」和「模型想得少但答对了」，也无法判断
    输出上限到底有没有被触及 —— 这个缺口曾让一次档位对照白跑（见 RESULTS.md）。
    """
    u = ctx.get("usage") or {}
    return {k: v for k, v in u.items() if isinstance(v, int) and v}


def tool_inputs(ctx: dict, name: str) -> list:
    """取某个工具的全部调用参数，判分时用得上（例如「有没有真的调 write 落盘」）。

    ⚠ opencode 的工具名与 CC 不同（小写：read/write/edit/bash/glob/grep），
      现有用例一律不按工具名判分，新写用例时也请优先看外部可观察行为。
    """
    return [t.get("input", {}) for t in ctx.get("tools", []) if t.get("name") == name]
