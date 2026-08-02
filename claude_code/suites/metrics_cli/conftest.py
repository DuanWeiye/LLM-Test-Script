# 让 tests 无需安装即可 import metrics（把项目根加入 sys.path）
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
