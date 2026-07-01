# 让 tests 无需安装即可 import telemetry_kit（把项目根加入 sys.path）
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
