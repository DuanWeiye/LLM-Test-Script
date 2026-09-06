#!/usr/bin/env python3
"""隐藏资产保管库：验收测试、参考答案要点这类「模型不该看到的东西」。

**为什么不用文件权限或沙箱**：原先靠 bwrap 把整个评测目录 tmpfs 遮空，代价是每次跑评测都要
`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`，跑完还得改回来 —— 太不方便，
而且忘了改回来就是长期降低本机安全性。

**现在的做法**：被测模型的工作目录是 /tmp 下的中性随机目录（见 core/workspace.py），
与评测框架没有任何路径关联；验收测试再以压缩+base64 形态存放，磁盘上 grep 不到
`def test_` / 断言值 / 设备 ID 这类特征串。判分时才在内存里解开、临时写进工作目录、跑完删除。

**定位要说清楚**：这是「防止模型顺手 grep 撞见答案」，不是密码学保护 —— 一个铁了心要
作弊的 agent 仍可能解开它。评测面对的是正常干活的模型，这个强度足够；真要更硬就得上容器。
"""
from __future__ import annotations

import base64
import json
import sys
import zlib
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent / "vault"


def _path(name: str) -> Path:
    return VAULT / f"{name}.bin"


def seal(name: str, payload: dict) -> Path:
    """把 {文件名: 源码} 存进保管库。"""
    VAULT.mkdir(exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    blob = base64.b64encode(zlib.compress(raw, 9))
    p = _path(name)
    p.write_bytes(blob)
    return p


def unseal(name: str) -> dict:
    """取出 {文件名: 源码}。"""
    p = _path(name)
    if not p.exists():
        raise FileNotFoundError(f"保管库里没有 {name}（应有 {p}）")
    return json.loads(zlib.decompress(base64.b64decode(p.read_bytes())).decode("utf-8"))


def has(name: str) -> bool:
    return _path(name).exists()


def names() -> list:
    return sorted(p.stem for p in VAULT.glob("*.bin")) if VAULT.exists() else []


# ---------- 命令行：编辑隐藏测试的正常流程 ----------
# 改隐藏测试时：先 dump 到临时目录改，改完 seal 回去，删掉明文。
def _cli():
    if len(sys.argv) < 2 or (sys.argv[1] != "list" and len(sys.argv) < 3):
        print("用法：\n"
              "  python3 -m core.vault seal <case_id> <文件...>   把明文文件存进保管库\n"
              "  python3 -m core.vault dump <case_id> <目录>      解出明文以便编辑\n"
              "  python3 -m core.vault list                       列出已存的用例\n")
        raise SystemExit(2)
    cmd = sys.argv[1]
    if cmd == "list":
        for n in names():
            payload = unseal(n)
            print(f"  {n:20} {len(payload)} 个文件: {', '.join(payload)}")
        return
    case_id = sys.argv[2]
    if cmd == "seal":
        payload = {}
        for f in sys.argv[3:]:
            p = Path(f)
            payload[p.name] = p.read_text(encoding="utf-8")
        out = seal(case_id, payload)
        print(f"已封存 {len(payload)} 个文件 → {out}")
    elif cmd == "dump":
        dst = Path(sys.argv[3])
        dst.mkdir(parents=True, exist_ok=True)
        for name, src in unseal(case_id).items():
            (dst / name).write_text(src, encoding="utf-8")
            print(f"  → {dst / name}")
    else:
        raise SystemExit(f"未知命令 {cmd}")


if __name__ == "__main__":
    _cli()
