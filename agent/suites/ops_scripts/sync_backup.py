#!/usr/bin/env python3
"""把模型目录同步到备份盘（rsync 包一层，加上超时保护）。"""
import subprocess
import sys
from pathlib import Path

SRC = Path.home() / "models"
DST = Path("/mnt/backup/models")


def sync(src=SRC, dst=DST, timeout=30):
    """跑一次 rsync。timeout 是整次同步的秒数上限，超时算失败。"""
    cmd = ["rsync", "-a", "--delete", f"{src}/", f"{dst}/"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"同步超过 {timeout}s 未完成"
    return p.returncode == 0, (p.stderr or "").strip()[-200:]


def main():
    ok, detail = sync()
    print(("同步完成" if ok else "同步失败：") + detail)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
