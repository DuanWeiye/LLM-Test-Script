"""本地调试入口。"""
from __future__ import annotations

import argparse

from .logview import LogView
from .render import render
from .session import DeviceSession
from .store import Store

DEMO = "dev-1,1,70.5;dev-2,2,81.0;dev-1,3,71.2;dev-3,4,66.8;"


def build_parser():
    ap = argparse.ArgumentParser(prog="panel")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="跑一遍演示数据并渲染面板")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "demo":
        store = Store()
        sess = DeviceSession(store)
        sess.connect()
        sess.feed(DEMO)
        n = sess.drain()
        sess.close()
        log = LogView()
        log.write(f"收到 {n} 条读数")
        print(render(store))
        print("-" * 8)
        print(log.render())


if __name__ == "__main__":
    main()
