# LLM Test Script

一套**本地大模型能力评测脚本**，分两个互补视角考同一批模型：

| 目录 | 名字 | 考什么 | 怎么接模型 |
|---|---|---|---|
| [`bare_llm/`](bare_llm/) | **纯裸测** | 模型**原始能力**：编码 / 工具判断 / 事实 / 抗幻觉 / 格式 / 多步推理 / 知识 / 超长上下文检索 | 直连任意 **OpenAI 兼容** `/chat/completions` 端点 |
| [`claude_code/`](claude_code/) | **接 Claude Code** | **真 agent 场景**：多轮工具编排、在真实 git 沙箱里改代码跑 pytest、缺参反问、深度诊断 | 用 Claude Code 当统一外壳，只换底层模型 |

两套用**同一批模型**跑，能对比出「裸模型能力」和「装进 agent 外壳后的实战表现」的差异——很多模型在裸测某维度弱，但在有完整脚手架的 agent 环境里并不复现，反之亦然。

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
└── claude_code/               # 接 Claude Code（真 agent 场景）
    ├── run_eval.py            #   运行引擎：bwrap 隔离沙箱 + stream-json 抓工具调用 + 判分
    ├── eval_cases.py          #   14 个用例定义 + 各自确定性判分
    ├── setup_sandbox.sh       #   把 sandbox 初始化成 git 基线（首次必跑）
    ├── sandbox/               #   合成项目 telemetry_kit + 各用例素材（评测在此隔离运行）
    └── settings.example/      #   Claude Code settings 占位示例（复制成 settings/ 自行填 key）
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

> 提示：温度全部固定 0；测速/长上下文数字取决于你的端点与硬件。

---

## Part 2 · 接 Claude Code `claude_code/`

用**同一个 Claude Code 外壳**，只把底层模型换掉，跑 14 个 agent 用例。每个用例在**隔离的 git 沙箱**里执行，跑前自动 `git reset` 还原，判分用确定性方法（pytest / 文件 diff / 断言；深度诊断题用 rubric 命中）。

### 前置

- **Claude Code CLI**（`claude` 在 PATH 中）。
- **bwrap**（bubblewrap）——用来把每次 `claude -p` 关进只看得到沙箱的命名空间，**防止模型 grep 到判分逻辑/答案作弊**（Ubuntu: `sudo apt install bubblewrap`）。
- 一个**带 pytest 的 Python 解释器**跑判分（默认用运行 `run_eval.py` 的解释器；也可 `export EVAL_PY=/path/to/python`）。
- 若测**非 Claude 模型**：需要一个把你的模型转成 **Anthropic 兼容 API** 的代理（如 [LiteLLM](https://github.com/BerriAI/litellm)）。**本仓库不含任何代理配置或 key**，请自行搭建。

### 步骤

**① 配 settings**：把 `settings.example/` 里的模板复制成 `settings/<model>.json`，填入你自己的地址与 key：

```bash
mkdir -p settings
cp settings.example/local-model.json.example settings/my-model.json   # 本地/自建模型（经 Anthropic 兼容代理）
cp settings.example/cloud-claude.json.example settings/claude-sonnet-4-6.json  # 云端 Claude 订阅直连
# 编辑 settings/*.json：model 名、ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN
```

> `settings/` 已被 `.gitignore` 忽略——**你的真实 key 不会被提交**。

**② 初始化沙箱**（首次必跑，让 run_eval 的还原机制可用）：

```bash
bash setup_sandbox.sh
```

**③ 放开 user namespace**（bwrap 隔离需要，Ubuntu 默认限制；评测后请恢复）：

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
# ……跑完评测后：
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=1
```

**④ 跑评测**：

```bash
# --models 须有对应 settings/<model>.json；--cases all 或逗号分隔用例 id；--k-default 覆盖每用例重复次数
python3 run_eval.py --models my-model --cases all --k-default 1 --stamp run1
python3 run_eval.py --models my-model --cases A1,C2,E1 --k-default 1 --stamp probe
```

结果写入 `results/results_<stamp>.json`（每用例 `pass_at_1`、`pass_k`、每次 runs 明细含工具列表/耗时/输出片段）。

### 14 个用例

| 维度 | 用例 |
|---|---|
| A 工具判断 | A1 该不该调 / A2 缺参反问 / A3 错误恢复 / A4 多工具编排 |
| B 多步可靠（默认 k=5）| B1 数据处理链 / B2 多文件功能 / B3 端到端 |
| C 代码 | C1 修 bug / C2 实现 percentile / C3 重构不破坏 / C4 代码问答 |
| D 约束·长程 | D1 五约束机检 / D2 长文档综合 |
| E 深度诊断（k=3）| E1 开卷（暴露答案文档目录，测主动找资料）/ E1I 闭卷（遮蔽，测纯推理） |

**E1 开卷**用来测「模型会不会主动去翻资料」。它依赖一个你自己的「答案文档目录」——用环境变量指定，闭卷时会被 bwrap 遮蔽：

```bash
export EVAL_ANSWER_DOCS=/path/to/你的知识库    # 不设则开卷等同闭卷
```

---

## 评测理念（几条踩过坑的经验）

- **看 `pass^k` 不只看 `pass@1`**：同一道难题重复跑 k 次、k 次全过才算稳。小模型 vs 顶级模型最大的差距往往在**一致性**，不在单次对错。
- **必须隔离防泄题**：`claude -p` 用 `--setting-sources project`（不加载用户级 CLAUDE.md）+ bwrap 遮蔽判分脚本与答案文档，否则模型会 grep 到答案「开卷作弊」。
- **关键词判对错必有假阳性**：越彻底的回答越会「主动提到 X 来排除 X」，朴素子串匹配会把高级回答误杀（本仓库的诊断判分对「排除语境」做了否定判定，可作参考）。
- **主观题别让被测模型自评**：幻觉诚实度 / 代码质量 / 翻译忠实度这类，脚本只收集产物，交人或独立更强模型盲评。

---

## 隐私与安全

- 仓库内**不含任何 API key、代理地址或个人配置**：`settings/` 被忽略、只提供 `settings.example/` 占位；所有脚本的端点均可用环境变量覆盖。
- `sandbox/` 里的公司/设备/人名/数值均为**评测用合成数据**，非真实信息。

## License

[MIT](LICENSE) © 2026 DuanWeiye
