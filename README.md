# LLM Test Script

一套**本地大模型能力评测脚本**，分两个互补视角考同一批模型：

| 目录 | 名字 | 考什么 | 怎么接模型 |
|---|---|---|---|
| [`bare_llm/`](bare_llm/) | **纯裸测** | 模型**原始能力**：编码 / 工具判断 / 事实 / 抗幻觉 / 格式 / 多步推理 / 知识 / 超长上下文检索 | 直连任意 **OpenAI 兼容** `/chat/completions` 端点 |
| [`claude_code/`](claude_code/) | **接 agent 外壳** | **真 agent 场景**：25 条用户口吻的模糊需求，只测外部可观察行为 —— 多轮工具编排、改代码跑隐藏验收、缺参反问、开卷/闭卷诊断 | 用 Claude Code 当统一外壳，只换底层模型 endpoint |

两套用**同一批模型**跑，能对比出「裸模型能力」和「装进 agent 外壳后的实战表现」的差异——很多模型在裸测某维度弱，但在有完整脚手架的 agent 环境里并不复现，反之亦然。

> **2026-08-02 第二套整体重构**：需求形态从「精确规格」换成「用户口吻的模糊需求」，判分口径换成 F2P/P2P 由基线快照自动划分，隔离方式换成**零特权**（不再需要 bwrap 与 `sudo sysctl`）。此前基于旧架构的结果不可与新版对比。
>
> 曾经支持的 codex / hermes 外壳依赖 bwrap，本次一并覆盖，等这套跑顺了再重做；旧实现在 git 历史 `git show 98d3a7a:claude_code/runners.py`。

> 起源：在一台 NVIDIA DGX Spark（GB10 / ARM64）上评测本地部署的多个 Qwen 系模型（经 llama.cpp / llama-swap 提供 OpenAI 兼容端点），顺带对照几个云端模型。脚本本身与具体硬件、具体模型无关，任何 OpenAI 兼容端点都能用。

---

## 目录结构

```
LLM-Test-Script/
├── bare_llm/                  # 纯裸测（直连 OpenAI 兼容端点）
│   ├── eval_lib.py            #   公共库：发请求 + 各类自动判分器 + 工具集
│   ├── full_eval.py           #   常规卷：编码/工具/事实幻觉/格式/三语
│   ├── full_eval_hard.py      #   难卷：硬算法/多步推理/更广知识/多约束指令/更难工具
│   ├── niah_lib.py            #   NIAH 公共库：造长文埋针 + 提问
│   └── niah_full.py           #   超长上下文大海捞针（4 长度 × 6 情景）
└── claude_code/               # 接 agent 外壳（真 agent 场景）
    ├── run_eval.py            #   引擎：baseline / oracle / self-check / judge / report / 评测
    ├── core/                  #   判分口径、基线快照、工作目录、保管库、LLM 裁判
    ├── cases/                 #   25 条用例定义（按维度分文件）
    ├── suites/                #   用例项目模板（7 个合成项目）
    ├── vault/                 #   隐藏验收测试（压缩存放，磁盘上 grep 不到）
    ├── baseline.json          #   基线快照：哪些检查项本来红（F2P）、哪些本来绿（P2P）
    ├── DESIGN.md              #   设计说明 + 用例清单 + 踩坑记录（接手先读这个）
    └── settings.example/      #   endpoint 配置占位示例（复制成 settings/ 自行填）
```

---

## 通用前置

- **Python 3.10+**（`bare_llm` 只用标准库，无需第三方依赖）。
- 一个能访问的模型端点（见各部分说明）。

---

## Part 1 · 纯裸测 `bare_llm/`

### 1. 指定端点
脚本默认连 `http://127.0.0.1:12345/v1`。用环境变量改成你的端点（须是 **OpenAI 兼容** 的 `/chat/completions`）：

```bash
export LLM_BASE_URL="http://你的地址:端口/v1"
```

对端点的要求：
- 常规/难卷的**工具题**需要端点支持 OpenAI `tools` 参数与 `tool_calls` 返回。
- NIAH 依赖返回体里的 `timings.prompt_n`（实际 token 数）与 `cache_prompt`（前缀缓存，llama.cpp 系有）；其它引擎没有也能跑，只是拿不到 prefill 统计、长文会更慢。

### 2. 跑常规卷 / 难卷

```bash
cd bare_llm
# 参数1 = 逗号分隔的模型名（须是端点认识的 model id）；参数2 = 结果文件标签（可选）
python3 full_eval.py      "my-model-a,my-model-b"  run1
python3 full_eval_hard.py "my-model-a,my-model-b"  run1
```

- 客观项（编码执行、工具 schema、关键词/格式）**自动判分**并打印。
- 主观项（幻觉诚实度、代码质量、翻译/摘要忠实度）会被收集到 `ab_judge_queue*.json`，**留给人或更强的模型盲评**——脚本不替你判主观题。
- 结果写入脚本目录下 `ab_results<标签>.json`。

### 3. 跑超长上下文大海捞针（NIAH）

```bash
cd bare_llm
python3 niah_full.py "my-model-a,my-model-b"
```

在一篇塞满**同款干扰项**的长文里埋 6 个不同深度（5%–95%）的「针」（访问码/负责人/日期/数量/英文限流/口令），4 个长度档（8K/64K/160K/224K token）各问一遍，看模型能不能精确捞出。结果写 `niah_results.json`。

> **采样：不指定任何采样参数**，由端点按各模型自己的官方推荐设定跑
> （llama.cpp 系在启动参数里配 `--temp/--top-p/--top-k`，云端 API 不传即用官方默认）。
> 温度 0 的贪心解码虽然确定性好，但偏离多数模型的 `generation_config`（明确 `do_sample=true`），
> 属于「没按说明书用」——对经 RL 对齐的模型可能系统性低估，有些模型在温度 0 下甚至无法正常工作。
> 代价是结果带采样方差，所以**每道题默认跑 3 次**（`EVAL_REPEAT` 可调），成绩记成「过了几次/3」。
> 想复现温度 0 的贪心对照：`EVAL_TEMPERATURE=0 EVAL_REPEAT=1`。
>
> 测速/长上下文数字取决于你的端点与硬件。

---

## Part 2 · 接 agent 外壳 `claude_code/`

用 **Claude Code 当统一外壳**，只把底层模型 endpoint 换掉，跑 25 条 agent 用例。
详细设计见 [`claude_code/DESIGN.md`](claude_code/DESIGN.md)。

### 用例长什么样

需求一律用**用户口吻**说，不给函数名、字段名、子命令名、算法：

> 这个小工具现在只能看平均温度和超限的设备。我想提前发现快要出问题的机器——就是那些温度在一路往上走的。
> 你给加到这个命令行工具里吧，具体怎么设计、叫什么名字、输出成什么样，你看着办。已经有的功能别弄坏。

判分因此只看**外部可观察行为**：先从 `--help` 里发现模型自己起的子命令名，再验证输出语义。
验收测试**对模型不可见**（压缩存在 `vault/`，判分时才临时注入、跑完删除）。

| 维度 | 条数 | 例子 |
|---|---|---|
| 工具纪律 | 5 | 信息不足该不该先问、跑失败会不会如实说、模糊又危险的指令怎么办 |
| 模糊新功能 | 5 | 趋势检测、日志撑坏界面、挑最新版本的后端、私密信息外置、导出 |
| 现象驱动修 bug | 4 | 「越用越卡」「断开重连就崩」「读出来是空的」——只给现象，定位靠模型 |
| 向后兼容 | 3 | 用户只提新需求，没提老调用方 —— 老行为坏了由 P2P 自动抓住 |
| 多步可靠（k=5） | 2 | 链条长、每步都要对、跑五次都要对 |
| 约束遵循 | 2 | 一条规矩写在需求里，一条写在 `CONTRIBUTING.md` 里（用户一个字没提） |
| 长程理解 | 2 | 跨文件溯源、长文档综合（带回滚记录之类的干扰项） |
| 深度诊断 | 2 | 同一个故障现场，开卷（项目里放资料）/ 闭卷（不放）对照 |

### 判分口径：F2P / P2P，由基线快照自动划分

- **F2P**（fail-to-pass）＝这次要求做到的事，基线下必然红。
- **P2P**（pass-to-pass）＝不许弄坏的事，基线下本来就绿。
- `partial = (f2p_passed + p2p_passed) / 总检查项`

归属**不用人手写**：`--baseline` 在干净项目上跑一遍全部检查项，红的算 F2P、绿的算 P2P。
这带来一个额外好处 —— **「用户没提但不该弄坏」的东西自动被守住**：
让模型给配置项改名时用户压根没说要兼容老配置，但「老键名读得出」在基线里是绿的，
只改名不做兼容，P2P 立刻红。

### 前置

- **`claude` CLI 在 PATH 中**。
- 一个**带 pytest 的 Python 解释器**跑判分（会自动探测；也可 `export EVAL_PY=/path/to/python`）。
- 开放题判分需要一个 **OpenAI 兼容端点**当裁判（默认 `http://127.0.0.1:12345/v1`，
  可用 `JUDGE_BASE` / `JUDGE_MODEL` / `JUDGE_KEY` 覆盖）。
- **不需要 bwrap，也不需要任何 `sudo` / `sysctl`。**
- 本仓库**不含任何代理配置或 key**，端点请自行搭建。

### 跑

```bash
cd claude_code

# ① 配 settings（settings/ 已被 .gitignore 忽略，真实 key 不会入库）
mkdir -p settings
cp settings.example/local-model.json.example  settings/my-model.json
# 编辑：model 名、ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN

# ② 跑前自检（前两步不花 LLM）
python3 run_eval.py --baseline      # 量基线 + 用例设计体检
python3 run_eval.py --oracle        # 参考解必须条条满分
python3 run_eval.py --judge-check   # 裁判自己先过考试

# ③ 正式评测（单模型约 79 次运行；**必须串行**，别同时跑多个模型）
python3 run_eval.py --models my-model --cases all --stamp run1

# ④ 开放题离线判分 + 出汇总表
python3 run_eval.py --judge  results/results_run1.json
python3 run_eval.py --report results/results_run1.json
```

报告里的格子是 `pass@1 (partial 均值)`；`⚠` 表示有运行被中断（超时/空输出），
`❗` 表示判分器自己出错 —— 这两种都**不是**「模型答错」，要单独查。

### 隔离怎么做的（零特权）

| 层 | 做法 | 挡住什么 |
|---|---|---|
| 工作目录 | 每次运行复制到 `/tmp/wk-<随机>/<项目名>`，**没有 .git** | 路径与评测框架无关联；模型也无法 `git diff` 反推基线 |
| 验收测试 | 压缩+base64 存 `vault/`，判分时才在内存解开 | 磁盘上 grep 不到 `def test_` 与断言值 |
| 外部资料 | 诊断题的资料放在项目内部，闭卷时整个目录不投放 | 不必遮蔽宿主任何目录 |
| 用户级配置 | `--setting-sources project` | 不加载 `~/.claude/CLAUDE.md`（曾经真的因此泄过题） |

保管库**不是加密**，挡的是「顺手 grep 撞见答案」；真要防铁了心作弊的 agent 得上容器。

### 加一条用例

1. 在 `suites/` 下放一个项目模板 —— **可见测试必须基线全绿**（有红测试等于一进门就剧透）
2. 写隐藏验收测试，`python3 -m core.vault seal <用例ID> <文件>` 封存
3. 在 `cases/<维度>.py` 里加一条 `Case`，配上参考解 `oracle`
4. `--baseline` → `--oracle` → `--self-check` 三关跑通才算能用

---

## 评测理念（几条踩过坑的经验）

- **看 `pass^k` 不只看 `pass@1`**：同一道难题重复跑 k 次、k 次全过才算稳。小模型 vs 顶级模型最大的差距往往在**一致性**，不在单次对错。
- **必须隔离防泄题**：`--setting-sources project`（不加载用户级 CLAUDE.md）+ 工作目录与评测框架无路径关联 + 验收测试不落明文，否则模型会 grep 到答案「开卷作弊」。
- **判分器自己也要有 oracle**：拿参考解跑一遍，不满分就说明框架坏了、这批模型分数全部不可信。本仓库这一版的**每一个**判分 bug 都是这么抓出来的，没有一个是靠眼睛看出来的。
- **裁判也要过考试**：用 LLM 判开放题之前，先拿标注好的样本（含同义改写的正确答案、以及「提到 X 只为排除 X」这种最容易假阳性的写法）考一考它，判不对就别用它的结论。
- **关键词判对错必有假阳性**：越彻底的回答越会「主动提到 X 来排除 X」，朴素子串匹配会把高级回答误杀（本仓库的诊断判分对「排除语境」做了否定判定，可作参考）。
- **主观题别让被测模型自评**：幻觉诚实度 / 代码质量 / 翻译忠实度这类，脚本只收集产物，交人或独立模型盲评。
- **需求写太细就测不出东西**：把字段名、函数名、算法都写进需求，模型只是打字员；真实场景里用户只说想要什么，「怎么做」本来就是 agent 该扛的部分。

---

## 隐私与安全

- 仓库内**不含任何 API key、代理地址或个人配置**：整个 `settings/`（含 `settings/codex`、`settings/hermes`）被忽略、只提供 `settings.example/` 占位；所有脚本的端点均可用环境变量覆盖。
- `suites/` 里的公司 / 设备 / 人名 / 数值 / 日志全是**评测用合成数据**。
  其中 `ops_scripts/notify.py` 里的 webhook、令牌、手机号是某道用例的靶子（「上 GitHub 前把这些摘出去」），
  **都是编的**；文件里不加「这是假的」注释，加了就等于剧透题目。

## License

[MIT](LICENSE) © 2026 DuanWeiye
