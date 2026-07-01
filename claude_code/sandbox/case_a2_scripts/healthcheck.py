"""健康检查：探测各服务端点是否在线。"""
import socket

TIMEOUT = 5  # 秒


def check(host, port):
    s = socket.create_connection((host, port), timeout=TIMEOUT)
    s.close()
    return True
