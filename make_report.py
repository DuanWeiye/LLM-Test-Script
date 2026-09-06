#!/usr/bin/env python3
"""把两套评测的结果汇总成一份给人看的 markdown 报告。

用法：
    python3 make_report.py  [-o 输出文件]

自己去 bare_llm/ 和 agent/results/ 找结果文件，按模型对齐成表。
裸卷成绩是「过了几次/总次数」，agent 卷是 `pass@1 (partial 均值)`。
"""
from __future__ import annotations

import argparse
import glob

import json
import os
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BARE = os.path.join(HERE, "bare_llm")
CC = os.path.join(HERE, "agent", "results")

# 模型 → 本轮结果文件的 tag。**必须精确指定**：早期温度 0 那轮的文件名
# （ab_results_hardqwen36.json）会被 `ab_results_*.json` 这种通配一并匹配到，
# 混进来就是拿两种采样条件的数字凑一张表 —— 不可比。
MODEL_TAG = {
    "qwen3.6-35b-a3b": "_qwen36a3b",
    "qwen3.6-35b-uncensored": "_uncensored",
    "laguna-s-2.1": "_laguna",
    "deepseek-v4-flash": "_dsflash",
    "qwythos-27b": "_qwythos",
    "qwen3.8-27b": "_qwen38",
    "qwen3.8-27b-q5": "_qwen38q5",
    # 2026-08-20：同一个 Qwen3.8-27B 换 NVFP4 权重 + SGLang 引擎跑的对照
    # （llama.cpp Q4_K_XL 那轮是 "qwen3.8-27b"）。题目、次数、采样口径与 Q4 轮完全一致，
    # 差别只有量化格式与推理引擎，所以两列可直接对比。
    "qwen3.8-27b-sglang": "_qwen38nvfp4",   # ← key 必须是端点认的 model id，结果 JSON 内部就用它当键
    # 同一份 NVFP4 权重，换 DSpark 投机解码（start-dspark.sh）跑的对照。
    # served-model-name 在 start.sh 里写死是 qwen3.8-27b-sglang，两轮结果 JSON 的 key 会撞，
    # 所以跑完把 DSpark 那份的 key 改成下面这个再入表。
    "qwen3.8-27b-sglang-dspark": "_qwen38nvfp4ds",
    # 2026-08-21：unsloth 08-19 重传了 Qwen3.8-27B-GGUF（imatrix 校准 45→1251 chunks、
    # 866 张量里 306 个换了量化类型）。"-v2" 是重量化后的新文件，"-old" 是同期复跑的旧文件
    # （llama-swap 里两个 key 并存，除模型文件外参数逐字相同）。
    # 为什么旧版要同期复跑而不直接用 08-17 的 "_qwen38"：同配置重跑已知有 ±7 分的采样噪声，
    # 隔四天的旧数字当基线判断不了「有没有提高」。
    # ⚠️ "-old" 那轮端点 model id 就是 "qwen3.8-27b"，结果 JSON 内部键需手工改成 "qwen3.8-27b-old"
    #    才不会和 08-17 那份撞键（同 DSpark 那轮的处理）。
    # 值可以是列表＝该模型跑了多轮，报告按题累加成 6 次/题（见 _merge_case）。
    "qwen3.8-27b-v2": ["_qwen38v2", "_qwen38v2r2"],
    "qwen3.8-27b-old": ["_qwen38old", "_qwen38oldr2"],
    # 2×2 归因用（内嵌官方模板那一列，跑完可撤）：08-17 那轮旧量化拿 159 分时用的还是 GGUF
    # 内嵌模板，08-20 才换成 froggeric，所以「旧量化今天只跑出 154/155」里混着换模板的影响。
    "qwen3.8-27b-native": ["_qwen38nat", "_qwen38natr2"],            # 旧量化 + 内嵌模板（＝复刻 08-17 口径）
    "qwen3.8-27b-v2-native": ["_qwen38v2nat", "_qwen38v2natr2"],     # 新量化 + 内嵌模板
    # froggeric v22.3 的工具克制修补版（关思考时不再示范 <think>、补回「没有合适函数就别调」）
    "qwen3.8-27b-v2-toolfix": ["_qwen38v2fix", "_qwen38v2fixr2"],
    # ── 2026-08-22：开思考的「采样口径」对照 ──────────────────────────────
    # 8-20 那轮开思考（_q4low / _nvfp4low）刻意沿用了关思考的采样(0.7/0.8/presence 1.5)，
    # 而 unsloth 对思考模式的推荐是 1.0/0.95/presence 0.0。下面两格在**同一份生产配置**
    # （08-19 新量化 + toolfix 模板）下同期跑，只差采样三项 —— 这是唯一能干净回答
    # 「采样值用错了到底有没有影响」的比法（拿 8-20 的 98/102 当基线不成立：那轮是
    #  旧量化 + froggeric 模板，差了三个变量）。两格都只跑难卷、reasoning_effort=low。
    "qwen3.8-27b-think-prod": "_q4lowprod",   # 开思考 · 生产采样(对照基线)
    "qwen3.8-27b-think-off":  "_q4lowoff",    # 开思考 · unsloth 官方思考采样
    # ── 2026-08-22：unsloth 自家 NVFP4（≠ 8-20 测的 RadixArk 那份）────────
    # 用来给「TT2 工具克制退化(0/10) 到底是 NVFP4 权重本身还是 SGLang 数值实现」
    # 这个 8-20 结尾没能拆开的悬案补一个证据点：换一份独立的 NVFP4 量化产物，
    # 若 TT2 仍崩 → 指向 SGLang 实现；若正常 → 指向 RadixArk 那份权重。
    "qwen3.8-27b-unsloth-nvfp4":       "_unvfp4",      # 关思考 · 全卷（对齐 Q4 全卷口径）
    "qwen3.8-27b-unsloth-nvfp4-think": "_unvfp4low",   # 开思考 · 难卷 · 官方思考采样
    # ── 2026-08-31：Tiel-Coder-35B-A3B ────────────────────────────────────
    # 血统 Qwen3.5-35B-A3B(基座) → ornith-ai/Ornith-1.5(真微调, 自动出题+RL 自改进)
    #      → peculiar-ragdoll(仅重量化 + Sharp 模板，权重没动)。跑的是 MTP 版 UD-Q8_K_XL。
    # 用 GGUF 内嵌的 Sharp 模板跑（不套本机 toolfix）——那模板是这个 build 的卖点之一，
    # 套掉就测不到它本来的样子；且模板效果与模型强相关，本来就不该跨模型推广。
    "tiel-coder-35b": ["_tiel", "_tielr2"],
    # 与 Tiel 同一天、同一份生产配置下**同期复跑**的 qwen3.6-35b-a3b 基线。
    # 为什么不直接用左边第一列（08-02 的 "_qwen36a3b"）当基线：那轮用的还是 GGUF 内嵌模板、
    # 也没有 --reasoning-budget，隔了近一个月配置漂了三处，拿它作差会把模板和预算的影响
    # 算到 Tiel 头上（同 08-21 重量化那轮「旧成绩不能当基线」的教训）。
    # ⚠️ 该轮端点 model id 就是 "qwen3.6-35b-a3b"，结果 JSON 内部键已手工改成下面这个，
    #    否则与 08-02 那份撞键（同 DSpark / qwen38-old 两轮的处理方式）。
    "qwen3.6-35b-a3b-0831": ["_q36base831", "_q36base831r2"],
    # ── 08-31 归因矩阵的另三格（结论见《评测报告-tiel-coder-35b-20260831.md》）──
    # Tiel 同时换了权重(Ornith)和模板(Sharp)两个变量，补成矩阵才能分清赖谁。
    # tiel-nt = 同一个 Sharp 模板、只用 chat_template_kwargs 关掉 terse 注入（最干净的单变量）。
    # 结论：模板扣 14 分(281→295)、权重扣 14 分(308→294，其中硬算法 −14、工具判断 +4)。
    "tiel-coder-35b-frog":  ["_tielfrog", "_tielfrogr2"],    # Tiel 权重 + froggeric v22.3
    "tiel-coder-35b-nt":    ["_tielnt", "_tielntr2"],        # Tiel 权重 + Sharp(terse=false)
    "qwen3.6-35b-a3b-frog": ["_q36frog", "_q36frogr2"],      # q36 权重 + froggeric v22.3
    # ── 08-31 第二轮：qwen3.6-35b-a3b 模板选型（主人「留最好的配置」）──────────
    # 四格：toolfix 298 / v22.3 308 / v22.4 308 / GGUF内嵌 303（每格两轮，除模板外参数逐字相同）。
    # v22.3 与 v22.4 **逐题完全相同**（两轮都 154，轮内波动 0）——v22.4 的三项改动在裸卷上碰不到。
    # 结论：生产已换 v22.4（分数打平时取新版，它修的是 agent 多工具场景的 prefix KV cache 分歧）。
    "q36-v224":   ["_v224", "_v224r2"],       # froggeric v22.4 ← 现生产
    "q36-native": ["_native", "_nativer2"],   # GGUF 内嵌官方模板（基准；有中途 system 静默丢弃硬伤，不可选）
    # 2026-09-05：35B 的**采样档位**对照（不是模板、不是量化）。35B 卡给了四档，本机生产一直用
    # 「Instruct(非思考)·reasoning tasks = 1.0/0.95/pp1.5」（有出处、不是抄错），
    # 本列＝换成「Instruct(非思考)·general = 0.7/0.80/pp1.5」，其余（权重/模板 v22.4/MTP/KV）逐字相同。
    # 基线就是 q36-v224（308/342），两列可直接对比。起因见 评测报告-flash-next采样口径-20260905.md。
    "q36-gen": ["_q36gen", "_q36genr2"],
    # ── 2026-09-02：Qwen3.8-Flash-Next（Qwen4exp 预览架构，unsloth UD-Q4_K_XL）────
    # 125B MoE(512 专家/激活 10+1，仅 6B 活跃) + 51B n-gram embedding + 4B MTP，总 177B。
    # 本机 128G 能跑的最高档：51B ngram 表在 GGUF 里是单个 26.82 GiB 张量
    # (per_layer_token_embd)，靠 --tensor-read-lazy 按需读盘不常驻，故常驻只 76.9 GiB。
    # 选型与参数说明见 ~/Documents/dgx/llama-swap-config.yaml 的同名块。
    # 模板用 GGUF 内嵌官方版：本机的 froggeric/toolfix 是给 Qwen3.6/3.8-27B 调的，
    # 模板效果与模型强相关、不该跨模型推广（同 Tiel-Coder 那轮的处理方式）。
    # 关思考、3 次/题，口径对齐现有各列。跑的是 -np 1 -c 262144 单并发配置。
    # 两轮独立 seed（第一轮 1-3，第二轮 EVAL_SEED_BASE=3 → 4-6），合并成 6 次/题。
    # 轮内波动仅 2 分（151/171 vs 153/171）——噪声底比 35B 那批（±5~7）小得多。
    "qwen3.8-flash-next": ["_flashnext", "_flashnextr2"],
    # 2026-09-04：同一份 UD-Q4_K_XL 权重复跑，与上面那两轮的差异只有两处 ——
    #   ① 挂上 MTP 投机解码（shared-Q8_0 头；换 unsloth 预编译后端后才支持 qwen4exp 的 MTP）
    #   ② KV cache 量化成 q8_0（上一轮漏了，本机另三个模型都有）
    # 并发/上下文（-np 1 -c 262144）、采样、模板、题目、次数逐字相同，故两列可直接对比。
    # 归因口径：MTP 是**无损**投机解码（主模型逐 token 验证，输出分布不变），所以分数若有差异
    # 只能归到 KV q8_0 或采样噪声（该模型轮内噪声底约 2 分）——不要把分差算到 MTP 头上。
    "qwen3.8-flash-next-mtp": ["_fnmtp", "_fnmtpr2"],
    # 2026-09-05：采样口径对照。上面两列（_flashnext / _fnmtp）跑的是服务端 temp 1.0 / top_p 0.95
    # / presence 1.5 —— 那是从 qwen3.6-35b-a3b 块抄来的组合，在 Flash-Next 的模型卡里**没有出处**
    # （它只给两套：Thinking 1.0/0.95/pp0.0，Instruct 0.7/0.80/pp1.5；本机跑的是 --reasoning off
    # 即非思考，本该用后者）。35B 那边不同：它的卡有第四档「非思考·推理任务 1.0/0.95/pp1.5」，
    # 所以 35B 的写法是对的、不受此列影响。
    # 本列＝同权重同 MTP 同 KV，**只把采样换成官方 Instruct 档**，其余逐字相同。
    # 裸卷脚本默认不发采样参数（eval_lib.apply_sampling），所以服务端这三项就是实际生效值。
    "qwen3.8-flash-next-instr": ["_fninstr", "_fninstrr2"],
    # 2026-09-04：qwen3.8-27b 的 **agent 卷**首测（此前它只有裸卷成绩）。
    # 为什么不并进上面的 "qwen3.8-27b"：那一列是 08-17 的旧量化 + GGUF 内嵌模板；
    # 本轮用的是当前生产配置＝v2 重量化权重 + qwen-fixed-v22.3-toolfix 模板 + draft-dflash。
    # 也不并进 "qwen3.8-27b-v2"：那列是 froggeric 模板跑的，而换 toolfix 正是冲着「工具克制」
    # 去的（froggeric 在 27B 上净扣 4~7 分且全扣在工具克制），而 agent 卷首个维度就是工具纪律
    # —— 混列会把模板差异算到别处。故独立成列，只有 agent 卷有数据（裸卷那格空＝没考，不是零分）。
    "qwen3.8-27b-prod": "_q38prod",
    # ── 2026-09-06：换壳 opencode + 裸卷改造后的**首轮正式评测**（三个模型）──────────
    # 为什么必须开新列、不能并进上面任何一列：
    #   · agent 卷外壳从 Claude Code 换成了 opencode（直连 llama-swap，不再过 LiteLLM），
    #     历史 agent 成绩与本轮不可比；
    #   · 裸卷这次拆了 HC/X 两个维度、新增 MT/LR/IFC 三卷，题目集变了。
    # 一个 tag 同时喂两卷（bare 读 ab_results{tag}.json、agent 读 results{tag}.json），
    # 所以同一列里既有裸卷也有 agent 卷成绩，不用像 handoff 草案那样拆成两列。
    "qwen3.6-35b-a3b-0906":    "_q36_0906",
    "qwen3.8-27b-0906":        "_q38_0906",
    "qwen3.8-flash-next-0906": "_fn_0906",
}

# 外部环境跑的结果：`agent/results/external_*.json`。
# 用途是把别处（别的机器、别的外壳部署）跑出来的 agent 卷成绩并进同一张表。
# **只收聚合值、原样照抄**：这类结果拿不到逐次运行明细，若反推 pass@1/partial
# 的原始精度再重算维度均值，会因四舍五入漂 0.01，跟来源文档对不上——
# 所以这里存的是已渲染好的格子文本，报告只负责摆位置，不再做任何算术。
# 文件形状见 external_example.json；缺哪块就少哪块，不会影响其它模型。
EXTERNAL_GLOB = "external_*.json"

# 维度显示名与顺序。
#
# ★ 2026-09-06 拆成「主卷 / 回归卷」两组。依据是历次成绩里的实测区分度
#   （近期模型的最高分与最低分之差）：
#
#     硬算法      58%~86%   28pp   ← 主力区分器
#     多约束指令  75%~100%  25pp
#     工具判断    82%~96%   14pp
#     ------------------------------ 以下已饱和，全模型几乎满分 ------------------
#     知识广度    89%~100%          事实  92%~100%      编码(三语) 89%~100%
#     多步推理    94%~100%          格式  97%~100%
#
#   饱和维度合计约 150/342 分是「死分」——所有模型都拿满，只会稀释区分度，
#   让真正的差距在总分里被摊薄。但它们**不删**：题目还照跑，只是移出选型视野，
#   改当回归测试用（新模型如果在这些基本功上退步，仍然要能立刻看见）。
#
#   ⚠ 往主卷加维度/加题前的判据（2026-09-06 订正过一次，记下修正的理由）：
#
#     判据是**模型之间拉不拉得开**，不是单个模型的绝对通过率。
#     最初写的是「本机最弱模型通过率落在 30~70%」，实践中立刻被打脸：
#     长上下文题 LR3 在 qwen3.6-35b-a3b 上 0/3、在 qwen3.8-27b 上 3/3 ——
#     按旧标准该被当成「太难」剔掉，可它恰恰是全卷最干净的区分器
#     （一个完全做不到、另一个稳定做到，比两个都 2/3 有信息量得多）。
#
#     所以正确的做法是**至少拿一强一弱两个模型标定**：
#       · 所有模型都接近满分  → 饱和，进回归卷（HC / MT1 / MT2 就是这么归的）
#       · 所有模型都接近全灭  → 废题，要改造（X5 长期全模型 0/6 属于这种）
#       · 模型之间拉得开      → 主卷，哪怕某个模型是 0/3
CORE_DIMS = OrderedDict([
    ("hardcode_x", "硬算法(高难 X)"), ("tool", "工具判断"), ("instruct", "多约束指令"),
    ("multiturn", "多轮一致性"), ("longctx", "长上下文推理"),
    ("conflict", "约束冲突"),
])
REGRESSION_DIMS = OrderedDict([
    ("multiturn_reg", "多轮基本功"), ("hardcode", "基础算法(HC)"),
    ("code", "编码(三语)"), ("fact", "事实"),
    ("format", "格式遵循"), ("reason", "多步推理"), ("knowledge", "知识广度"),
])
# 合并视图：失分明细表、维度名查找仍按老口径用这个，顺序＝主卷在前
BARE_DIMS = OrderedDict(list(CORE_DIMS.items()) + list(REGRESSION_DIMS.items()))
OPEN_DIMS = {"halluc": "抗幻觉(盲评)", "breadth": "广度(盲评)"}


def _merge_case(dst, cid, rec):
    """同一模型的多轮结果按题合并：pass/n 累加、samples 拼接。

    为什么要累加而不是覆盖：一个模型可能跑了不止一轮（例如 2026-08-21 的重量化对照，
    seed 1-3 与 seed 4-6 各一轮），合起来才是 6 次/题的成绩。只跑一轮时这个函数
    退化成原来的覆盖行为，其它模型不受影响。
    注意 bool 是 int 的子类，早期结果里 pass 是 bool（1/1 口径），不能参与累加。
    """
    old = dst.get(cid)
    ints = lambda r: type(r.get("pass")) is int and type(r.get("n")) is int
    if isinstance(old, dict) and isinstance(rec, dict) and ints(old) and ints(rec):
        merged = dict(old)
        merged["pass"] = old["pass"] + rec["pass"]
        merged["n"] = old["n"] + rec["n"]
        merged["samples"] = (old.get("samples") or []) + (rec.get("samples") or [])
        dst[cid] = merged
    else:
        dst[cid] = rec


def _load(paths):
    """读一批结果文件，合并成 {model: {case_id: rec}}。"""
    out = defaultdict(dict)
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for model, cases in data.items():
            if not isinstance(cases, dict):
                continue
            for cid, rec in cases.items():
                _merge_case(out[model], cid, rec)
    return out


def _load_external():
    """读 agent/results/external_*.json，返回 {model: rec}（按文件名排序）。"""
    out = OrderedDict()
    for path in sorted(glob.glob(os.path.join(CC, EXTERNAL_GLOB))):
        if os.path.basename(path) == "external_example.json":
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for model, rec in data.items():
            if isinstance(rec, dict):
                out[model] = rec
    return out


def _tags(m):
    """一个模型的结果标签。可以是一个字符串，也可以是多轮的标签列表。"""
    t = MODEL_TAG[m]
    return [t] if isinstance(t, str) else list(t)


def _bare_paths(models, kind=""):
    """本轮各模型的裸卷结果路径。kind='_hard' 取难卷。多轮的模型返回多个路径。"""
    return [os.path.join(BARE, f"ab_results{kind}{tag}.json")
            for m in models if m in MODEL_TAG for tag in _tags(m)]


def _rate(rec):
    """一条用例的通过率与「几/几」文本。pass 可能是次数(新版)或 bool(旧版)。"""
    p, n = rec.get("pass"), rec.get("n")
    if p is None:
        return None, None                      # 盲评题，不自动判分
    if isinstance(p, bool):
        return (1.0 if p else 0.0), ("1/1" if p else "0/1")
    n = n or 1
    return (p / n if n else 0.0), f"{p}/{n}"


def _norm_dim(cid, rec):
    """把结果记录归到显示维度。

    ★ 2026-09-06：HC1~HC8（基础算法）与 X1~X6（高难算法）在结果文件里都写着
      `dim="hardcode"`，混成一个维度。实测这两组的区分度差了一个数量级：

        HC 基础题   96%~100%（细粒 0.95~1.00）  ← 彻底饱和，零区分度
        X  高难题    8%~78% （细粒 0.40~0.98）  ← 跨度 70pp，全卷最强的区分器

      混在一起时 HC 的满分把 X 的差距稀释成 28pp。在报表层按题号前缀重新归类，
      历史结果 JSON 一个字都不用改就能享受这个拆分。
    """
    dim = rec.get("dim")
    if dim == "hardcode" and cid.startswith("X"):
        return "hardcode_x"
    return dim


def _dim_cell(cases, dim):
    """算一个模型在一个维度上的格子文本。

    除了老的全或无口径（通过次数/总次数），只要该维度的题带了 `partial_mean`
    （编码类题由 run_code_verdict 逐条断言算出来的），就同时给出细粒度均分。
    这个数一直在结果文件里存着，只是以前没往表里放 —— 而它恰恰是饱和区和地板区
    唯一还能分出高下的信号。
    """
    got = tot = 0
    parts = []
    for cid, rec in cases.items():
        if _norm_dim(cid, rec) != dim:
            continue
        r, _ = _rate(rec)
        if r is None:                      # 盲评题不自动判分
            continue
        p, n = rec.get("pass"), rec.get("n") or 1
        got += p if not isinstance(p, bool) else int(p)
        tot += n if not isinstance(p, bool) else 1
        pm = rec.get("partial_mean")
        if isinstance(pm, (int, float)):
            parts.append(pm)
    if not tot:
        return "—"
    cell = f"{got}/{tot} ({got/tot:.0%})"
    if parts:
        cell += f" ·细粒 {sum(parts)/len(parts):.2f}"
    return cell


def bare_section(models):
    """裸卷：常规卷 + 难卷合并成一张维度表 + 一张失分明细表。"""
    normal = _load(_bare_paths(models))
    hard = _load(_bare_paths(models, "_hard"))
    merged = defaultdict(dict)
    for src in (normal, hard):
        for m, cases in src.items():
            merged[m].update(cases)

    lines = []
    have = [m for m in models if m in merged]
    if not have:
        return ["_（没有找到裸卷结果）_", ""]

    # ---- 主卷：还有区分度的维度，选型看这张 ----
    lines += ["### 主卷（选型依据）", "",
              "格子是 `通过次数/总次数 (百分比)`；带 `·细粒 N` 的是**逐条断言**的细粒度均分 —— "
              "全或无口径下「能跑但边界条件错」和「根本跑不起来」都记 0 分，"
              "细粒度分能在这种地板区里继续拉开差距（X5 那种全模型 0/6 的题全靠它）。", ""]
    lines += ["| 维度 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    for dim, label in CORE_DIMS.items():
        lines.append("| " + " | ".join([label] + [_dim_cell(merged[m], dim) for m in have]) + " |")
    lines.append("")

    # ---- 回归卷：已饱和的基本功，只用来发现退步 ----
    lines += ["### 回归卷（已饱和，不计入选型）", "",
              "这些维度近期模型几乎都满分，留着是为了**发现退步**：某个模型在这里掉下来，"
              "说明基本功出了问题，值得单独查一眼。不要拿它们的分数去比模型强弱。", ""]
    lines += ["| 维度 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    for dim, label in REGRESSION_DIMS.items():
        lines.append("| " + " | ".join([label] + [_dim_cell(merged[m], dim) for m in have]) + " |")
    lines.append("")

    # 失分明细：任何模型没拿满的题都列出来
    lines += ["**没拿满分的题**（空白＝该模型满分）", "",
              "| 题 | 考点 | " + " | ".join(have) + " |", "|---|---|" + "---|" * len(have)]
    all_ids = OrderedDict()
    for m in have:
        for cid in merged[m]:
            all_ids.setdefault(cid, _norm_dim(cid, merged[m][cid]))
    for cid, dim in all_ids.items():
        cells, imperfect = [], False
        for m in have:
            rec = merged[m].get(cid)
            if not rec:
                cells.append("—")
                continue
            r, txt = _rate(rec)
            if r is None:
                cells.append("盲评")
                continue
            cells.append(txt if r < 1.0 else "")
            if r < 1.0:
                imperfect = True
        if imperfect:
            lines.append(f"| {cid} | {BARE_DIMS.get(dim, OPEN_DIMS.get(dim, dim))} | "
                         + " | ".join(cells) + " |")
    lines.append("")
    return lines


def cc_section(models):
    """agent 卷：逐用例 + 逐维度。"""
    # 同样按 tag 精确读：早期那轮（C1 改名前）的 results_qwen36.json 不该混进来
    data = _load([os.path.join(CC, f"results{tag}.json")
                  for m in models if m in MODEL_TAG for tag in _tags(m)])
    have = [m for m in models if m in data]
    ext = _load_external()
    cols = have + [m for m in ext if m not in have]
    if not cols:
        return ["_（没有找到 agent 卷结果）_", ""]

    order, dims = [], OrderedDict()
    for m in have:
        for cid, rec in data[m].items():
            if cid not in order:
                order.append(cid)
                dims[cid] = rec.get("dim", "")
    # 外部结果里有、本地这轮没跑的用例也要占一行
    for rec in ext.values():
        for cid in rec.get("cases", {}):
            if cid not in order:
                order.append(cid)
                dims[cid] = rec.get("case_dims", {}).get(cid, "")

    def _cell(m, cid):
        if m in have:
            rec = data[m].get(cid)
            if not rec or rec.get("pass_at_1") is None:
                return "—"
            return f"{rec['pass_at_1']:.2f} ({rec['partial_mean']:.2f})"
        return ext[m].get("cases", {}).get(cid, "—")

    lines = ["| 用例 | 维度 | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for cid in order:
        lines.append("| " + " | ".join([cid, dims.get(cid, "")]
                                       + [_cell(m, cid) for m in cols]) + " |")
    lines.append("")

    # 维度汇总
    by_dim = OrderedDict()
    for cid in order:
        by_dim.setdefault(dims.get(cid, ""), []).append(cid)
    lines += ["| 维度 | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for dim, cids in by_dim.items():
        row = [dim]
        for m in cols:
            if m in ext:
                row.append(ext[m].get("dims", {}).get(dim, "—"))
                continue
            recs = [data[m][c] for c in cids if c in data[m] and data[m][c].get("pass_at_1") is not None]
            if not recs:
                row.append("—")
                continue
            p1 = sum(r["pass_at_1"] for r in recs) / len(recs)
            pm = sum(r["partial_mean"] for r in recs) / len(recs)
            row.append(f"{p1:.2f} ({pm:.2f})")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 行为观察
    lines += ["**行为观察**", "",
              "| 模型 | 总运行 | 平均工具数 | 平均耗时 | 中断 | 判分器故障 |", "|---|---|---|---|---|---|"]
    for m in cols:
        if m in ext:
            b = ext[m].get("behavior")
            if b:
                lines.append(f"| {m} | {b.get('runs','—')} | {b.get('tools','—')} | "
                             f"{b.get('wall','—')} | {b.get('aborted','—')} | "
                             f"{b.get('grader_error','—')} |")
            continue
        runs = [r for rec in data[m].values() for r in rec.get("runs", [])]
        if not runs:
            continue
        n = len(runs)
        tools = sum(r.get("n_tools", 0) for r in runs) / n
        wall = sum(r.get("wall", 0) for r in runs) / n
        ab = sum(1 for r in runs if r.get("aborted"))
        ge = sum(1 for r in runs if r.get("grader_error"))
        lines.append(f"| {m} | {n} | {tools:.1f} | {wall:.0f}s | {ab} | {ge} |")
    lines.append("")

    # 外部结果的出处与口径，必须写在表边上，免得跟本地这轮混着读
    notes = [f"> **{m}**：{ext[m]['note']}" for m in ext if ext[m].get("note")]
    if notes:
        lines += notes + [""]
    for m in ext:
        extra = ext[m].get("extra_md")
        if extra:
            lines += extra + [""]
    return lines


def niah_section(models):
    """NIAH：{model: {长度档: {actual_tokens, recall, cells:[{depth,hit,...}]}}}。

    本地那几个跑在 niah_results.json，走别的 endpoint 的（云端）用 NIAH_TAG 另存，
    这里把所有 niah_results*.json 合起来读。
    """
    data = {}
    for path in sorted(glob.glob(os.path.join(BARE, "niah_results*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for m, v in d.items():
            data.setdefault(m, {}).update(v)
    have = [m for m in models if m in data]
    if not have:
        return ["_（没有找到 NIAH 结果）_", ""]

    buckets = []
    for m in have:
        for b in data[m]:
            if b not in buckets:
                buckets.append(b)
    buckets.sort(key=lambda x: int(x))

    lines = ["每档 6 根针（深度 5%/20%/40%/60%/80%/95%），格子是召回数。", "",
             "| 长度档 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    failed = []
    for b in buckets:
        row = [f"{int(b)//1000}K"]
        for m in have:
            cell = data[m].get(b)
            if not cell:
                row.append("—")
                continue
            cells = cell.get("cells", [])
            errs = [c for c in cells if c.get("err")]
            # 整档全是请求错误 ≠ 模型没召回。多半是造文按固定字符/token 估算，
            # 中文压缩率低的 tokenizer 实际 token 冲破了服务端 -c 上限（HTTP 400）。
            if cells and len(errs) == len(cells):
                row.append("**请求失败**")
                failed.append((m, b, errs[0].get("err", "")[:40]))
            else:
                row.append(f"{cell['recall']}/6")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    if failed:
        lines.append("> **注意**：标「请求失败」的格子是**请求没发成功**，不是模型没召回 —— "
                     "不能当成长上下文能力弱来读。")
        for m, b, err in failed:
            lines.append(f"> - {m} 在 {int(b)//1000}K 档：`{err}`"
                         f"（该模型 tokenizer 对中文压缩率低，实际 token 冲破了上下文上限）")
        lines.append("")

    # 实际 token 数：档位标签只是目标值，不同 tokenizer 差很多
    lines += ["实际 prompt token 数（档位标签只是目标，中文压缩率因 tokenizer 而异）：", "",
              "| 长度档 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    for b in buckets:
        row = [f"{int(b)//1000}K"]
        for m in have:
            cell = data[m].get(b)
            row.append(str(cell.get("actual_tokens", "?")) if cell else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 哪个深度最容易丢
    lines += ["按深度看（所有档位累计命中/尝试）：", "",
              "| 深度 | " + " | ".join(have) + " |", "|---|" + "---|" * len(have)]
    depths = [0.05, 0.20, 0.40, 0.60, 0.80, 0.95]
    for d in depths:
        row = [f"{int(d*100)}%"]
        for m in have:
            hit = tot = 0
            for b in data[m].values():
                for c in b.get("cells", []):
                    if abs(c.get("depth", -1) - d) < 1e-6:
                        tot += 1
                        hit += 1 if c.get("hit") else 0
            row.append(f"{hit}/{tot}" if tot else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "RESULTS.md"))
    # ★ 默认展示集必须与「表里该有哪些列」保持同步。这里曾经长期只列前 8 个，
    #   于是无参数跑一次 make_report.py 就把 RESULTS.md 里其余列**静默冲掉**
    #   （2026-09-04 又踩了一次）。新增模型入表时，除了 MODEL_TAG 还要往这里追加。
    #   注：MODEL_TAG 里的中间对照组（*-native / *-think-* / *-old 等）故意不进默认展示集，
    #   要看它们就显式传 --models。
    ap.add_argument("--models", default="qwen3.6-35b-a3b,qwen3.6-35b-uncensored,"
                                        "laguna-s-2.1,deepseek-v4-flash,qwythos-27b,"
                                        "qwen3.8-27b,qwen3.8-27b-q5,qwen3.8-27b-sglang,"
                                        "qwen3.8-27b-v2,qwen3.6-35b-a3b-0831,"
                                        "qwen3.6-35b-a3b-frog,q36-v224,q36-native,q36-gen,"
                                        "tiel-coder-35b,tiel-coder-35b-nt,tiel-coder-35b-frog,"
                                        "qwen3.8-flash-next,qwen3.8-flash-next-mtp,"
                                        "qwen3.8-flash-next-instr,"
                                        "qwen3.8-27b-prod,"
                                        "qwen3.6-35b-a3b-0906,qwen3.8-27b-0906,"
                                        "qwen3.8-flash-next-0906")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    out = ["# 评测结果", "",
           "两套卷子、同一批模型。裸卷考模型自己会什么，agent 卷考把活交给它能不能干成。", "",
           "- **裸卷**：不指定采样参数，按各模型**服务端**配的设定跑；每题 3 次，成绩记「过了几次/3」。",
           "  （★ 服务端配的未必等于官方推荐：`qwen3.8-flash-next` / `-mtp` 两列吃的是 temp 1.0 / top_p 0.95，",
           "  而 Flash-Next 官方非思考档是 0.7 / 0.80 —— 那组值是从 35B 块抄来的、在它的卡里没有出处。",
           "  `-instr` 列是改回官方档的复测，+21 分。见《评测报告-flash-next采样口径-20260905.md》。）",
           "  跑过两轮独立 seed 的模型按题合并成 6 次（分母如实写出，百分比仍可横比）。",
           "- `qwen3.8-27b` 那列是 2026-08-17 用 **GGUF 内嵌模板**跑的；`qwen3.8-27b-v2` 是 08-19 **重量化**",
           "  + **froggeric 模板**、两轮 6 次/题。两列之间同时变了量化与模板，2×2 拆解见",
           "  《评测报告-qwen3.8-27b-重量化与模板-20260821.md》。",
           "- **裸卷分主卷与回归卷**（2026-09-06 起）：主卷是仍有区分度的三个维度，选型只看它；",
           "  回归卷是已饱和的五个维度（近期模型几乎全满），题还照跑，但只用来发现退步。",
           "  拆分依据是实测区分度，见 make_report.py 里 CORE_DIMS 的注释。",
           "- **agent 卷**：统一外壳只换 endpoint（★下表为换壳前的 Claude Code 时代成绩）；",
           "  格子是 `pass@1 (partial 均值)`，"
           "  pass@1 是全或无（F2P 全过且 P2P 一条没坏），partial 是检查项通过比例。",
           "- **外部并进来的模型**（agent 卷表格下方有引用块标注）可能只跑了其中一卷，",
           "  没跑的卷子里不会出现它那一列——是没考，不是考了零分。", "",
           "---", "", "## 一、裸卷", ""]
    out += bare_section(models)
    out += ["---", "", "## 二、Agent 卷（Claude Code 外壳 · 历史成绩）", "",
            "> **★ 2026-09-06 外壳已从 Claude Code 换成 opencode**（动机：降低模型对单一外壳的",
            "> 特化优化污染结论；顺带去掉 LiteLLM 那层 Anthropic 协议翻译）。**下表是换壳前的",
            "> 数字，与今后的 agent 卷成绩不可比**，保留作历史参照。细节见 `agent/DESIGN.md` 第〇节。", ""]
    out += cc_section(models)
    out += ["---", "", "## 三、超长上下文（NIAH · 已退役）", "",
            "> **★ 已饱和退役**：全部模型在 4 个长度档 × 6 个深度上**全部 6/6 命中**，",
            "> 零区分度。纯检索式的大海捞针对现在这批模型已经不构成挑战，保留数据作历史参照，",
            "> 不再作为选型依据。要测长上下文能力应改用**多跳取证 / 变量追踪**这类需要",
            "> 组合多处信息才能作答的题（造文基建 `niah_lib.py` 可以直接复用）。", ""]
    out += niah_section(models)

    open(args.out, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("报告写入", args.out)


if __name__ == "__main__":
    main()
