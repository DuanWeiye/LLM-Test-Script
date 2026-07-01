"""定时备份：打包目录并上传。"""
import subprocess

TIMEOUT = 30  # 秒


def backup(path):
    subprocess.run(["tar", "czf", "backup.tgz", path], timeout=TIMEOUT, check=True)
