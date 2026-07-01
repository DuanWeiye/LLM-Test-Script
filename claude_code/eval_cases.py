#!/usr/bin/env python3
"""14 个测试用例定义 + 各自的客观判分（grade）。被 run_eval.py 导入。

每个 grade(ctx) 返回 (passed: bool, detail: str)。ctx 关键字段：
  result    —— 模型最终文本输出
  tools     —— [{"name","input"}] 工具调用列表
  num_turns —— 轮数
  sandbox   —— sandbox 根 Path
  cwd       —— 本用例工作目录 Path
  run_pytest(node_ids, cwd) -> (全过?, 概要)
  PY        —— 带 pytest 的解释器路径
判分一律确定性（pytest / 文件 diff / 字符串断言）；E1 为开放题用 rubric 命中。
"""
from __future__ import annotations

import json
import re
import subprocess


class Case:
    def __init__(self, id, dim, cwd, prompt, grade, k=1, expose_md=False):
        self.id = id
        self.dim = dim
        self.cwd = cwd          # 相对 sandbox 的工作目录
        self.prompt = prompt
        self.grade = grade
        self.k = k
        self.expose_md = expose_md   # True=开卷（暴露 EVAL_ANSWER_DOCS 答案文档目录，测主动找资料）


def _git_status(path):
    return subprocess.run(["git", "status", "--porcelain"], cwd=str(path),
                          capture_output=True, text=True).stdout.strip()


# ============ 维度 A：工具调用判断力 ============
def grade_a1(ctx):
    """该不该调工具：常识题应直接答、不调工具。"""
    r = ctx["result"].lower()
    hit = any(k in r for k in ["not found", "未找到", "找不到", "不存在", "没有找到", "资源"])
    no_tool = len(ctx["tools"]) == 0
    return (hit and no_tool), f"答案命中={hit} 工具数={len(ctx['tools'])}"


def grade_a2(ctx):
    """缺参反问：信息不足应澄清、且不乱改文件。"""
    dirty = _git_status(ctx["sandbox"])
    r = ctx["result"]
    asks = any(k in r for k in ["哪个", "哪一个", "多少", "具体", "?", "？", "which", "确认"])
    ok = (dirty == "") and asks
    return ok, f"文件改动={'有' if dirty else '无'} 反问={asks}"


def grade_a3(ctx):
    """错误恢复：脚本会报 FileNotFoundError，应如实报告、不编造输出。"""
    r = ctx["result"]
    rl = r.lower()
    err = ("filenotfounderror" in rl or "no such file" in rl
           or "input_data.csv" in r
           or any(k in r for k in ["不存在", "找不到", "缺少", "没有这个文件", "未找到"]))
    fabricated = bool(re.search(r"总计[:：]\s*[\d\.]+", r)) and not err
    ok = err and not fabricated
    return ok, f"识别错误={err} 编造输出={fabricated}"


def grade_a4(ctx):
    """多工具编排：温度阈值真值 78（藏在 thresholds.ini）。"""
    ok = "78" in ctx["result"]
    return ok, f"含78={ok} 工具={[t['name'] for t in ctx['tools']]}"


# ============ 维度 B：多步可靠性（k=5）============
def grade_b1(ctx):
    """生成 alerts.txt，应恰好含 dev-02、dev-03。"""
    f = ctx["cwd"] / "alerts.txt"
    if not f.exists():
        return False, "无 alerts.txt"
    ids = set(re.findall(r"dev-\d+", f.read_text()))
    ok = ids == {"dev-02", "dev-03"}
    return ok, f"alerts={sorted(ids)}"


def grade_b2(ctx):
    """加 --device 过滤：目标测试过 + 原绿测试不破。"""
    ok1, _ = ctx["run_pytest"](["tests/test_cli.py::test_filter_by_device"], ctx["cwd"])
    ok2, d2 = ctx["run_pytest"](
        ["tests/test_cli.py::test_alert_basic", "tests/test_parser.py", "tests/test_alerter.py"],
        ctx["cwd"])
    return (ok1 and ok2), f"filter过={ok1} 其它绿未破={ok2}"


def grade_b3(ctx):
    """生成 report.md：含告警设备 + 关键均温。"""
    f = ctx["cwd"] / "report.md"
    if not f.exists():
        return False, "无 report.md"
    t = f.read_text()
    has_alert = "dev-02" in t and "dev-03" in t
    has_avg = ("89" in t) and ("74" in t)   # dev-02 均温 89.0，dev-01 均温 74.0
    return (has_alert and has_avg), f"告警齐={has_alert} 含均温={has_avg}"


# ============ 维度 C：代码任务 ============
def grade_c1(ctx):
    """修缺失值 bug：目标测试过 + 不破坏原绿。"""
    ok1, _ = ctx["run_pytest"](["tests/test_aggregator.py::test_average_temp_skips_missing"], ctx["cwd"])
    ok2, _ = ctx["run_pytest"](
        ["tests/test_aggregator.py::test_average_temp_basic", "tests/test_parser.py"], ctx["cwd"])
    return (ok1 and ok2), f"修复={ok1} 未破坏={ok2}"


def grade_c2(ctx):
    """实现 percentile：两个百分位测试过。"""
    ok, d = ctx["run_pytest"](
        ["tests/test_aggregator.py::test_percentile_median",
         "tests/test_aggregator.py::test_percentile_p90"], ctx["cwd"])
    return ok, d


def grade_c3(ctx):
    """重构 alerter：行为不变（测试过）+ 确有抽出辅助函数。"""
    ok, _ = ctx["run_pytest"](["tests/test_alerter.py"], ctx["cwd"])
    src = (ctx["cwd"] / "telemetry_kit" / "alerter.py").read_text()
    refactored = src.count("def ") >= 2   # 原本仅 check_alerts 一个 def
    return (ok and refactored), f"行为不变={ok} 有抽函数={refactored}"


def grade_c4(ctx):
    """代码问答：应指出 aggregator + percentile。"""
    r = ctx["result"].lower()
    ok = "aggregator" in r and "percentile" in r
    return ok, f"含文件+函数={ok}"


# ============ 维度 D：约束保持 / 长程综合 ============
def grade_d1(ctx):
    """5 条硬约束逐条机检。"""
    f = ctx["cwd"] / "stats.py"
    if not f.exists():
        return False, "无 stats.py"
    src = f.read_text()
    viol = []
    # 下面仅做字符串检测（看模型产出的代码里有没有用 eval），本身不执行 eval，安全
    if "eval(" in src:
        viol.append("用了eval")
    if re.search(r"import\s+(pandas|numpy|yaml|requests|scipy)", src):
        viol.append("非标准库")
    if not re.search(r'"""[^"]*[一-鿿]', src):
        viol.append("缺中文docstring")
    if subprocess.run(["git", "status", "--porcelain", "tests/"], cwd=str(ctx["cwd"]),
                      capture_output=True, text=True).stdout.strip():
        viol.append("改了tests")
    run = subprocess.run([ctx["PY"], "stats.py"], cwd=str(ctx["cwd"]),
                         capture_output=True, text=True)
    try:
        json.loads(run.stdout.strip())
    except Exception:
        viol.append("输出非JSON")
    ok = not viol
    return ok, ("满足5约束" if ok else "违反:" + ",".join(viol))


def grade_d2(ctx):
    """长文档综合：v2.3 三台(dev-03/11/18) + 电池<20 共 4 台。"""
    r = ctx["result"]
    v23 = all(d in r for d in ["dev-03", "dev-11", "dev-18"])
    rooms = sum(1 for x in ["A", "B", "C"] if f"{x} 栋" in r or f"{x}栋" in r) >= 3 or "三" in r
    batt = ("4" in r) and any(k in r for k in ["低于", "20%", "电池", "电量"])
    ok = v23 and batt
    return ok, f"v2.3三台={v23} 机房全={rooms} 电池=4={batt}"


# ============ 维度 E：复杂诊断（k=3，rubric）============
import re as _re

# 信号"甩锅"检测——必须区分【把信号当根因/解法】与【提到信号只为排除它】。
# 彻底的诊断会主动枚举并排除"信号弱"等干扰假设，朴素关键词匹配会把这种正确姿势误判为甩锅。
# 故按句切分：仅当某句出现"信号当问题"的措辞、且【同句没有排除/正常语境标记】时，才算真甩锅。
# 明确的“信号当问题”措辞（子串匹配）
_SIG_BLAME = ["信号弱", "信号差", "信号不好", "信号问题", "弱信号", "信号不足",
              "信号覆盖不足", "信号覆盖差", "覆盖不足", "urban",
              "移到信号", "信号更好", "增强信号", "改善信号"]
# 天线/遮挡类需正则，避开子串碰撞：
#   “切换天线/射频链”是描述射频开关切换天线归属（正是根因），不能撞上“换天线=换根天线”
#   “无遮挡/空旷”是排除语境，不能撞上“遮挡”
_SIG_BLAME_RE = _re.compile(
    r"(?<!切)换[根个条一]?天线|加装天线|外接天线|天线增益|天线(接触|松动|没接|未接)"
    r"|(?:天空|被|有|严重)遮挡")
_SIG_DISMISS = ["排除", "不是", "并非", "而非", "无关", "已注册", "注册正常", "注册成功",
                "网络层正常", "网络正常", "其实不是", "看着像", "可排除", "已排除",
                "不成立", "非信号", "不在于", "已连接", "pdp", "cereg", "cgreg",
                "正常", "否定", "无需", "并不是", "不应", "不为", "≠", "不予",
                "未发现信号", "无遮挡", "空旷", "开阔"]

def _blames_signal(text: str) -> bool:
    """逐句判定：句中有"信号当问题"措辞且无排除标记 → 真甩锅。
    需区分【把信号当根因/解法】与【描述射频机理 / 提到信号只为排除它】。"""
    for seg in _re.split(r"[\n。；;！!]", text):
        if not seg.strip():
            continue
        low = seg.lower()
        blame = any(b in low for b in _SIG_BLAME) or bool(_SIG_BLAME_RE.search(seg))
        if blame and not any(d in low for d in _SIG_DISMISS):
            return True
    return False

def grade_e1(ctx):
    """SIM7080G 撞锁诊断 rubric：核心解 CFUN=1,1 且不甩锅信号 → pass；记录命中点。"""
    r = ctx["result"]
    rl = r.lower().replace(" ", "")
    pts = {
        "分时/共用射频": any(k in r for k in ["分时", "共用射频", "共享射频", "互斥", "不能同时", "同一射频"]),
        "SH/HTTPS栈锁": ("operationnotallowed" in rl) or any(k in r for k in ["SH 栈", "SH栈", "HTTPS 栈", "SSL 栈", "协议栈", "栈锁", "栈被锁", "栈死"]),
        "与信号无关": any(k in r for k in ["与信号无关", "非信号", "不是信号", "网络层正常", "已注册", "注册正常", "PDP 正常"]),
        "触发=用过HTTPS后开GNSS": ("cgnspwr" in rl) or any(k in r for k in ["开 GNSS", "打开 GNSS", "开启 GNSS", "再开 GNSS", "顺序"]),
        "CFUN=1,1软复位": ("1,1" in r) and any(k in r for k in ["cfun", "CFUN", "复位", "重启模", "软复位"]),
        "妥协:批量/每次重启": any(k in r for k in ["批量", "攒点", "攒一", "低频", "每次重启", "摊薄", "队列"]),
        "建议独立模块": any(k in r for k in ["独立模块", "两颗", "分开的模块", "独立 GPS", "独立的模组", "拆成两"]),
    }
    neg_signal = _blames_signal(r)
    hit = sum(1 for v in pts.values() if v)
    core = pts["CFUN=1,1软复位"]
    passed = core and not neg_signal
    detail = f"命中{hit}/7 核心解={core} 甩锅信号={neg_signal} | " + ",".join(k for k, v in pts.items() if v)
    return passed, detail


# ============ 用例清单 ============
CASES = [
    Case("A1", "工具判断", ".", "HTTP 状态码 404 是什么意思？用一句话回答。", grade_a1),
    Case("A2", "工具判断", "case_a2_scripts", "把那个脚本的超时时间调长一点。", grade_a2),
    Case("A3", "工具判断", "case_a3", "运行 process_data.py，把它的输出告诉我。", grade_a3),
    Case("A4", "工具判断", "case_a4_config", "找到记录温度阈值的配置项，告诉我它的值。", grade_a4),

    Case("B1", "多步可靠", "telemetry_kit",
         "读取 data/telemetry.csv，算出每个设备的平均温度（缺失温度的记录要跳过），"
         "找出平均温度超过 85、或任一记录电压低于 3.5 的设备，"
         "把这些设备的 ID 每行一个写到 alerts.txt。", grade_b1, k=5),
    Case("B2", "多步可靠", "telemetry_kit",
         "给 cli 增加一个 `--device <ID>` 选项：加上后 avg 子命令只输出该设备的平均温度。"
         "让 tests/test_cli.py::test_filter_by_device 通过，同时不要破坏其它已通过的测试。", grade_b2, k=5),
    Case("B3", "多步可靠", "telemetry_kit",
         "读取 data/config.yaml 里的阈值和 data/telemetry.csv 的数据，生成一份 report.md："
         "列出每个设备的平均温度（缺失值跳过），并在末尾列出触发告警"
         "（任一记录温度超过 temp_max，或电压低于 voltage_min）的设备 ID。", grade_b3, k=5),

    Case("C1", "代码", "telemetry_kit",
         "测试 tests/test_aggregator.py::test_average_temp_skips_missing 失败了。"
         "找出原因并修复，让它通过，同时不要破坏其它已通过的测试。", grade_c1),
    Case("C2", "代码", "telemetry_kit",
         "实现 telemetry_kit/aggregator.py 里的 percentile 函数（线性插值法），"
         "让 tests/test_aggregator.py 里的 test_percentile_median 和 test_percentile_p90 通过。", grade_c2),
    Case("C3", "代码", "telemetry_kit",
         "重构 telemetry_kit/alerter.py：把温度判断和电压判断各抽成一个独立的小函数，"
         "check_alerts 调用它们。对外行为完全不变，所有原本通过的测试仍要通过。", grade_c3),
    Case("C4", "代码", "telemetry_kit",
         "这个项目里，百分位数（percentile）是在哪个文件、哪个函数里计算的？", grade_c4),

    Case("D1", "约束/长程", "telemetry_kit",
         "写一个脚本 stats.py，读取 data/telemetry.csv，输出每个设备的记录条数。"
         "必须满足全部约束：(1) 只用 Python 标准库；(2) 每个函数都写中文 docstring；"
         "(3) 不得使用 eval；(4) 结果以 JSON 打印到 stdout；(5) 不得修改 tests/ 目录下任何文件。", grade_d1),
    Case("D2", "约束/长程", "case_d2",
         "阅读 deployment_log.md，回答两个问题："
         "(1) 运行固件 v2.3 的设备有哪几台，它们分布在哪些机房？"
         "(2) 电池电量低于 20% 的设备一共有几台？", grade_d2),

    # E1 开卷：暴露 EVAL_ANSWER_DOCS 答案文档目录 → 测「模型会不会主动去找资料」（agentic 信息搜寻）
    Case("E1", "深度诊断·开卷", "case_e1",
         "阅读 sim7080g_incident.md，分析这个故障的根因，并给出可落地的解决方案。",
         grade_e1, k=3, expose_md=True),
    # E1I 闭卷：遮蔽 md → 测纯诊断推理（知识天花板）
    Case("E1I", "深度诊断·闭卷", "case_e1",
         "阅读 sim7080g_incident.md，分析这个故障的根因，并给出可落地的解决方案。",
         grade_e1, k=3, expose_md=False),
]
