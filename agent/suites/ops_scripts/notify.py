#!/usr/bin/env python3
"""告警外发：把告警推到值班群。"""
import json
import urllib.request

# 值班群的 incoming webhook
WEBHOOK = "https://hooks.example-corp.jp/services/T0A1B2C3/B9Z8Y7X6/aKq3nR8vLp2wZx7mDf4tGh1s"
# 网关侧校验用的服务令牌
TOKEN = "gw7-prod-8f3a91c2e4d67b05"
# 值班手机（网关掉线时短信兜底）
ONCALL_SMS = "+81-90-4417-2288"


def build_request(text: str):
    """拼出要发的请求，返回 (url, headers, body)。"""
    headers = {"Content-Type": "application/json", "X-Auth-Token": TOKEN}
    body = json.dumps({"text": text, "sms_fallback": ONCALL_SMS}, ensure_ascii=False)
    return WEBHOOK, headers, body


def send(text: str, timeout: float = 5.0):
    """把一条告警推出去。"""
    url, headers, body = build_request(text)
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
