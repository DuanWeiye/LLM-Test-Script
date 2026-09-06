#!/usr/bin/env python3
"""每次运行的工作目录：从用例模板复制一份到 /tmp 的中性目录里。

替代了原先「一个共享 git 仓库 + git reset --hard 还原」的做法，三个理由：

1. **git 仓库本身是泄题面**：模型可以 `git log` / `git diff` 看出哪些是「原始基线」、
   哪些是它自己刚改的，甚至从提交历史里看出用例意图。复制出来的目录没有 .git，什么都看不出。
2. **还原更彻底**：删目录重新复制，不存在 `git clean` 漏掉的残留状态。
3. **路径不暴露评测框架**：目录名形如 `/tmp/wk-1a2b3c4d/telemetry_kit`，与本评测框架无关联，
   模型没有任何线索能顺着 cwd 摸到隐藏验收测试。这是删掉 bwrap（及其 sudo 依赖）的关键一环。
"""
from __future__ import annotations

import filecmp
import os
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = ROOT / "suites"
# 运行期垃圾，比对文件树时一律忽略
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git")
_NOISE_PARTS = {"__pycache__", ".pytest_cache", ".git"}


def _is_noise(rel: Path) -> bool:
    return any(part in _NOISE_PARTS for part in rel.parts) or rel.suffix == ".pyc"


def template_of(suite: str) -> Path:
    p = SUITES / suite
    if not p.is_dir():
        raise FileNotFoundError(f"用例模板不存在：{p}")
    return p


def prepare(suite: str, drop=None) -> Path:
    """复制一份干净的用例项目，返回工作目录（模型的 cwd）。

    drop 里的相对路径会在复制后删掉 —— 开卷/闭卷对照用同一套素材：
    开卷保留 docs/（测模型会不会主动去翻资料），闭卷把 docs/ 拿掉（测纯推理天花板）。
    这样两道题共用一份现场描述，不必维护两份几乎相同的模板。
    """
    src = template_of(suite)
    base = Path("/tmp") / f"wk-{secrets.token_hex(4)}"
    dst = base / src.name
    shutil.copytree(src, dst, ignore=IGNORE)
    for rel in (drop or []):
        target = dst / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    return dst


def cleanup(work: Path):
    """删掉整个运行目录（work 的父目录就是本次专用的 /tmp/wk-xxx）。"""
    try:
        base = work.parent
        if base.parent == Path("/tmp") and base.name.startswith("wk-"):
            shutil.rmtree(base, ignore_errors=True)
        else:                                   # 防御：路径不对劲就只删项目目录本身
            shutil.rmtree(work, ignore_errors=True)
    except Exception:
        pass


def sweep_stale(max_age_s: int = 6 * 3600) -> int:
    """清理历史遗留的运行目录（进程被 kill 时会留下），返回清掉几个。"""
    import time
    now, n = time.time(), 0
    for p in Path("/tmp").glob("wk-*"):
        try:
            if p.is_dir() and now - p.stat().st_mtime > max_age_s:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except Exception:
            pass
    return n


def restore(work: Path, suite: str, rel_paths) -> list:
    """判分前把指定路径从模板还原回去，返回实际被覆盖的路径。

    **为什么需要**：可见的基线测试是模型能改的。改测试让它变绿，是最典型的一种
    「把验收标准改掉」——比如某道题要求给配置项改名，基线测试里恰好绑着老名字，
    模型顺手把测试改成新名字，P2P 就假绿了。验收标准必须由评测方说了算，
    所以跑测试之前统一还原（模型改了什么仍照实记在 diff 里，作为行为观察保留）。
    """
    src = template_of(suite)
    touched = []
    for rel in (rel_paths or []):
        s, d = src / rel, work / rel
        if not s.exists():
            continue
        if s.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d, ignore=IGNORE)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        touched.append(str(rel))
    return touched


def _rel_files(root: Path) -> set:
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _NOISE_PARTS]
        for fn in filenames:
            rel = Path(dirpath, fn).relative_to(root)
            if not _is_noise(rel):
                out.add(rel)
    return out


def diff_against_template(work: Path, suite: str, drop=None) -> dict:
    """把工作目录与原始模板逐文件比对。

    替代原先的 `git status --porcelain` —— 判「模型有没有乱动文件」用得上
    （例如「信息不足时应当先反问，而不是直接动手改」这类用例）。
    返回 {"added": [...], "modified": [...], "deleted": [...]}，路径为相对 str。

    `drop` 要和 `prepare()` 传的保持一致：闭卷题本来就没投放 docs/，
    不排掉的话这些文件会被算成「模型删的」（闭卷诊断题第一次跑就撞上了）。
    """
    src = template_of(suite)
    a, b = _rel_files(src), _rel_files(work)
    for rel in (drop or []):
        rel = Path(rel)
        a = {p for p in a if p != rel and rel not in p.parents}
    added = sorted(str(p) for p in (b - a))
    deleted = sorted(str(p) for p in (a - b))
    modified = sorted(str(p) for p in (a & b)
                      if not filecmp.cmp(src / p, work / p, shallow=False))
    return {"added": added, "modified": modified, "deleted": deleted}


def is_untouched(work: Path, suite: str) -> bool:
    """模型是否完全没改动过项目文件。"""
    d = diff_against_template(work, suite)
    return not (d["added"] or d["modified"] or d["deleted"])
