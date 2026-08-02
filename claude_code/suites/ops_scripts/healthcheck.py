#!/usr/bin/env python3
"""探活推理服务：请求一次健康检查端点，不通就记一条告警。"""
import json
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:12345/health"
TIMEOUT = 5           # 秒，探活请求的等待上限
ALERT_LOG = Path(__file__).parent / "logs" / "alert.log"


def probe(url=ENDPOINT, timeout=TIMEOUT):
    """请求健康检查端点，返回 (是否正常, 说明)。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main():
    ok, detail = probe()
    if not ok:
        ALERT_LOG.parent.mkdir(exist_ok=True)
        with open(ALERT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "health_fail", "detail": detail},
                                ensure_ascii=False) + "\n")
    print(("OK " if ok else "FAIL ") + detail)


if __name__ == "__main__":
    main()
