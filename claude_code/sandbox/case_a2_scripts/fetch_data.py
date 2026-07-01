"""从远端拉取遥测数据。"""
import urllib.request

TIMEOUT = 10  # 秒


def fetch(url):
    return urllib.request.urlopen(url, timeout=TIMEOUT).read()
