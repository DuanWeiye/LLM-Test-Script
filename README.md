# LLM Test Script

一套**本地大模型能力评测脚本**，分两个互补视角考同一批模型：

| 目录 | 名字 | 考什么 | 怎么接模型 |
|---|---|---|---|
| [`bare_llm/`](bare_llm/) | **纯裸测** | 模型**原始能力**：编码 / 工具判断 / 事实 / 抗幻觉 / 格式 / 多步推理 / 知识 / 超长上下文检索 | 直连任意 **OpenAI 兼容** `/chat/completions` 端点 |
| [`claude_code/`](claude_code/) | **接 agent 外壳** | **真 agent 场景**：多轮工具编排、在真实 git 沙箱里改代码跑 pytest、缺参反问、深度诊断 | 用 agent CLI（Claude Code / Codex / Hermes）当统一外壳，只换底层模型 |

两套用**同一批模型**跑，能对比出「裸模型能力」和「装进 agent 外壳后的实战表现」的差异——很多模型在裸测某维度弱，但在有完整脚手架的 agent 环境里并不复现，反之亦然。

第二套支持三种可插拔外壳（`--runner claude|codex|hermes`），换外壳不动隔离与判分。⚠️ **注意：目前只有 Claude Code 已实机验证；Codex / Hermes 的适配已按官方文档写好，但尚未在本机实测**——用前请照 [Part 2](#part-2--接-agent-外壳-claude_code) 末尾的《合并前验证清单》逐项核对。

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
    ├── run_eval.py            #   运行引擎：--runner 选外壳 + bwrap 隔离沙箱 + 抓工具调用 + 判分
    ├── runners.py             #   可插拔「外壳驱动」：claude / codex / hermes 三个
    ├── eval_cases.py          #   14 个用例定义 + 各自确定性判分（与外壳无关）
    ├── setup_sandbox.sh       #   把 sandbox 初始化成 git 基线（首次必跑）
    ├── sandbox/               #   合成项目 telemetry_kit + 各用例素材（评测在此隔离运行）
    └── settings.example/      #   各外壳配置占位示例（复制成 settings/ 自行填）
        ├── local-model.json.example / cloud-claude.json.example   # Claude Code
        ├── codex/config.toml.example                              # Codex
        └── hermes/config.yaml.example                             # Hermes
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

## Part 2 · 接 agent 外壳 `claude_code/`

用**同一个 agent CLI 外壳**当脚手架，只把底层模型换掉，跑 14 个 agent 用例。每个用例在**隔离的 git 沙箱**里执行，跑前自动 `git reset` 还原，判分用确定性方法（pytest / 文件 diff / 断言；深度诊断题用 rubric 命中）。

支持三种可插拔外壳，用 `--runner` 选：

| runner | 外壳 | 状态 |
|---|---|---|
| `claude` | Claude Code（默认） | ✅ 已实机验证 |
| `codex`  | OpenAI Codex CLI | ⚠️ 适配已写、**尚未实机验证** |
| `hermes` | Nous Hermes Agent | ⚠️ 适配已写、**尚未实机验证** |

> **架构**：外壳调用抽象在 `runners.py`（每个外壳一个驱动，负责命令行与输出解析）；sandbox 还原、bwrap 反作弊隔离、判分逻辑三个外壳**共用**——换外壳只换这一层，再加第四个外壳只需实现一个驱动。

### 三种外壳的关键差异

| | Claude Code | Codex CLI | Hermes Agent |
|---|---|---|---|
| headless 命令 | `claude -p` | `codex exec` | `hermes -z` |
| 机器可读输出 | `--output-format stream-json` | `--json`（JSONL 事件） | 弱：`-z` 只出最终文本 |
| 工具轨迹 | stream-json 里 `tool_use` | JSONL `item.completed` | 需 `hermes sessions export` 补采 |
| 选模型 | `--settings <model>.json` | `-m <model>`（供应商走 config 默认） | `-m provider/model` |
| 免批准 | `--permission-mode bypassPermissions` | `--dangerously-bypass-approvals-and-sandbox` | `--yolo` |
| 配置位置 | `settings/<model>.json` | `settings/codex/config.toml`（经 `CODEX_HOME`） | `settings/hermes/config.yaml`（bwrap 绑成 `~/.hermes`） |
| **模型端点协议** | Anthropic 兼容 | **仅 Responses API** ⚠️ | OpenAI chat/completions 即可 |

**最大的坑 —— Codex 只吃 Responses API**：2026-02 起 Codex 的 `wire_api` 只支持 `responses`。本机 llama-swap / llama.cpp 只有 chat/completions，所以给 Codex 用**必须多搭一层网关**（如 [LiteLLM](https://github.com/BerriAI/litellm)）把本地模型转出一个 Responses 面，`config.toml` 的 `base_url` 指向该网关。**Hermes 没有这个限制，可直接指 `:12345`。**（`bare_llm` 是绕过外壳直接打 chat/completions，也不受此限。）

### 通用前置

- 对应外壳的 **CLI 在 PATH 中**（`claude` / `codex` / `hermes`）。
- **bwrap**（bubblewrap）——把每次外壳运行关进只看得到沙箱的命名空间，**防止模型 grep 到判分逻辑/答案作弊**（Ubuntu: `sudo apt install bubblewrap`）。
- 一个**带 pytest 的 Python 解释器**跑判分（默认用运行 `run_eval.py` 的解释器；也可 `export EVAL_PY=/path/to/python`）。
- **本仓库不含任何代理配置或 key**，网关/端点请自行搭建。

### 步骤

**① 配 settings（按外壳选一种，`settings/` 已被 `.gitignore` 忽略——真实 key 不会被提交）**

```bash
mkdir -p settings

# —— Claude Code ——（需一个把模型转成 Anthropic 兼容 API 的代理，如 LiteLLM）
cp settings.example/local-model.json.example  settings/my-model.json            # 本地/自建模型
cp settings.example/cloud-claude.json.example settings/claude-sonnet-4-6.json   # 云端 Claude 订阅直连
# 编辑 settings/*.json：model 名、ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN

# —— Codex ——（需一个 Responses 兼容网关，并 export LOCAL_LLM_KEY=<网关key>）
mkdir -p settings/codex
cp settings.example/codex/config.toml.example settings/codex/config.toml
# 编辑：base_url 指向你的 Responses 网关、env_key 名对上你 export 的变量

# —— Hermes ——（直连本机 llama-swap chat/completions，模型上下文需 ≥ 64k）
mkdir -p settings/hermes
cp settings.example/hermes/config.yaml.example settings/hermes/config.yaml
# 编辑：base_url 指向 :12345、provider=custom
```

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
# --runner 选外壳（默认 claude）；--models 须有对应外壳的 settings；
# --cases all 或逗号分隔用例 id；--k-default 覆盖每用例重复次数
python3 run_eval.py --runner claude --models my-model --cases all --k-default 1 --stamp base
python3 run_eval.py --runner claude --models my-model --cases A1,C2,E1 --stamp probe
python3 run_eval.py --runner codex  --models qwen-agentworld          --cases all --stamp cx
python3 run_eval.py --runner hermes --models custom/qwen-agentworld   --cases all --stamp hm
```

结果写入 `results/results_<runner>_<stamp>.json`（文件名带 runner，三套互不覆盖；每用例含 `pass_at_1`、`pass_k`、每次 runs 明细：工具列表/耗时/输出片段）。

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

### 已知限制（Codex / Hermes）

1. **Hermes 工具轨迹不可靠**：`hermes -z` 只吐最终文本。工具列表靠事后 `hermes sessions export` 导出 JSONL 再解析，其字段形状需实机核实。采不到时驱动置 `tools_unknown=True`，`run_eval` 会在该次结果 `detail` 前加「[工具轨迹未采集,需人工复核]」，**绝不把「没采到」静默当成「没调工具」**。
   - 受影响的判分：**A1**（要求「常识题不调工具」）依赖工具数为 0，Hermes 上须人工复核；其余用例看**文件产物 / 最终文本 / git 改动**，不依赖工具数，正常可用。
2. **Codex 需要 Responses 网关**：没有网关就跑不了本地模型（见上）。这是部署问题，不是脚本问题。
3. **bwrap 额外绑定**：codex/hermes 可能往各自 home 之外写缓存。目前只暴露 `CODEX_HOME` / `~/.hermes` + sandbox + `/tmp`；若实测报「只读文件系统」，按提示在 `runners.py` 对应驱动补一条 `--bind`。
4. **Hermes 的 `worktree.enabled` 键名**按文档推测写就，实机请对照官方 `cli-config.yaml.example` 校正，确保它**不**另建 git worktree（否则判分读不到模型改动）。

### 合并前验证清单（Codex / Hermes 本机务必逐项实测）

- [ ] `codex exec --json` 里，最终答复确实来自 `item.completed` 且 `item.type=="agent_message"` 的 `text`；工具事件类型名与 `runners.py::CodexRunner` 解析的一致（`command_execution`/`file_change`/`mcp_tool_call`）。
- [ ] `codex exec -m <model>` 能正确落到 `config.toml` 的默认 `model_provider`；`--skip-git-repo-check` 与 `--dangerously-bypass-approvals-and-sandbox` 均被接受、且自带沙箱确实关闭（能写 sandbox）。
- [ ] LiteLLM（或其它网关）的 `/responses` 面对本地模型可用，Codex 握手成功。
- [ ] `hermes -z "<prompt>" --yolo -m provider/model` 能无人值守跑完、只输出最终文本、且**真的改了 sandbox 文件**。
- [ ] `hermes sessions export <out.jsonl>` 能导出最近会话，其 JSONL 工具字段与 `runners.py::HermesRunner._collect_tools` 的兜底解析对得上（对不上就照实际字段改）。
- [ ] bwrap 把 `settings/hermes` 绑成 `~/.hermes` 后，Hermes 确实读到了我们的 `config.yaml`（模型/端点正确）。
- [ ] 三个外壳各随便跑一两个用例（如 `--cases A3,C2`），确认 `results_<runner>_*.json` 结构正常、判分合理。

实测跑通、看到真实输出后，把本清单勾掉并更新本节。

---

## 评测理念（几条踩过坑的经验）

- **看 `pass^k` 不只看 `pass@1`**：同一道难题重复跑 k 次、k 次全过才算稳。小模型 vs 顶级模型最大的差距往往在**一致性**，不在单次对错。
- **必须隔离防泄题**：`claude -p` 用 `--setting-sources project`（不加载用户级 CLAUDE.md）+ bwrap 遮蔽判分脚本与答案文档，否则模型会 grep 到答案「开卷作弊」。
- **关键词判对错必有假阳性**：越彻底的回答越会「主动提到 X 来排除 X」，朴素子串匹配会把高级回答误杀（本仓库的诊断判分对「排除语境」做了否定判定，可作参考）。
- **主观题别让被测模型自评**：幻觉诚实度 / 代码质量 / 翻译忠实度这类，脚本只收集产物，交人或独立更强模型盲评。

---

## 隐私与安全

- 仓库内**不含任何 API key、代理地址或个人配置**：整个 `settings/`（含 `settings/codex`、`settings/hermes`）被忽略、只提供 `settings.example/` 占位；所有脚本的端点均可用环境变量覆盖。
- Codex 的会话/日志（写在 `CODEX_HOME=settings/codex`）与 Hermes 的会话导出（写在 `settings/hermes`）也都落在被忽略的 `settings/` 下，不会入库。
- `sandbox/` 里的公司/设备/人名/数值均为**评测用合成数据**，非真实信息。

## License

[MIT](LICENSE) © 2026 DuanWeiye
