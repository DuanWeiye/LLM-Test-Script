# 分支 `codex-hermes`：把评测外壳扩展到 Codex / Hermes

本分支在原有 **Claude Code 外壳** 之外，把 `claude_code/` 那套 agent 评测适配到另外两个 agent CLI 外壳：

- **codex** —— OpenAI Codex CLI（`codex exec`）
- **hermes** —— Nous Research Hermes Agent（`hermes`）

同一批 14 个用例、同一套 sandbox 隔离与判分逻辑不变，只把「用哪个 CLI 当外壳」这一层换掉。

> ⚠️ **诚实声明**：本机没有装 codex / hermes、也没有搭 Responses 网关，**下面的适配代码尚未实机跑通**，
> 是按两者官方文档写的、结构完整的适配层。合并前请照最后一节《验证清单》逐项实测。
> 已做的只有 Python 语法/导入检查与 CLI 参数解析（`--runner {claude,codex,hermes}` 已生效）。

---

## 一、两套脚本各要改什么？

### `bare_llm/`（纯裸测）—— 不用改
纯裸测直接打 OpenAI 兼容的 `/chat/completions`，**与外壳无关**。想测 codex/hermes 背后那个模型，
直接 `export LLM_BASE_URL=...` 指过去即可，零改动。

> 小提示：Codex 自身要求 Responses API（见下），但 `bare_llm` 是**绕过外壳直接打模型端点**的，
> 所以它只认 chat/completions，和 Codex 的 Responses 限制互不相干。

### `claude_code/`（接 agent 外壳）—— 框架化改造
原本 `run_eval.py` 里把「怎么调 claude、怎么解析 stream-json」写死了。本分支把这层抽出来：

```
claude_code/
├── runners.py          ← 新增：可插拔「外壳驱动」（claude / codex / hermes 三个）
├── run_eval.py         ← 改：新增 --runner，编排逻辑复用；sandbox/bwrap/判分全不变
├── eval_cases.py       ← 未改：14 个用例与判分与外壳无关
└── settings.example/
    ├── codex/config.toml.example    ← 新增：Codex 供应商 + 默认模型配置示例
    └── hermes/config.yaml.example   ← 新增：Hermes 模型/后端配置示例
```

**为什么抽成 `runners.py` 而不是复制三份脚本**：sandbox 还原、bwrap 反作弊隔离、判分是**外壳无关**的，
只该有一份；会变的只是「命令行怎么拼 + 输出怎么解析」。抽成统一接口后，以后再加第四个外壳只需实现一个类。

每个外壳驱动实现两件事：
- `check(model, settings)` —— 预检配置是否就位；
- `__call__(...)` —— 跑一次，返回统一结构 `{result, tools, tools_unknown, num_turns, usage, is_error, wall, ...}`。

隔离「策略」（整根只读 + tmpfs 遮蔽评测内部/答案文档 + 暴露 sandbox）由 `run_eval` 统一提供，
各外壳只额外贡献自己的 home 目录绑定（`~/.claude` / `CODEX_HOME` / `~/.hermes`）与具体命令行。

---

## 二、三个外壳的关键差异

| | Claude Code | Codex CLI | Hermes Agent |
|---|---|---|---|
| headless 命令 | `claude -p` | `codex exec` | `hermes -z` |
| 机器可读输出 | `--output-format stream-json` | `--json`（JSONL 事件） | 弱：`-z` 只出最终文本 |
| 工具轨迹 | stream-json 里 `tool_use` | JSONL `item.completed` | 需 `hermes sessions export` 补采 |
| 选模型 | `--settings <model>.json` | `-m <model>`（供应商走 config 默认） | `-m provider/model` |
| 免批准 | `--permission-mode bypassPermissions` | `--dangerously-bypass-approvals-and-sandbox` | `--yolo` |
| 配置位置 | `settings/<model>.json` | `CODEX_HOME/config.toml` | `~/.hermes/config.yaml`（无 `--config`，故 bwrap 绑过去） |
| **模型端点协议** | Anthropic 兼容 | **仅 Responses API** ⚠️ | OpenAI chat/completions 即可 |

**最大的坑 —— Codex 只吃 Responses API**：2026-02 起 Codex 的 `wire_api` 只支持 `responses`。
本机 llama-swap / llama.cpp 只有 chat/completions，所以要给 Codex 用，**必须多搭一层网关**
（如 LiteLLM）把本地模型转出一个 Responses 面，`config.toml` 的 `base_url` 指向该网关。
Hermes 没有这个限制，可直接指 `:12345`。

---

## 三、怎么跑

三种外壳共用前置（见 README「Part 2」）：`bwrap`、带 pytest 的解释器、初始化过的 sandbox、
放开 user namespace（`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`，跑完恢复 =1）。

### Claude（和原来一样）
```bash
cd claude_code
python3 run_eval.py --runner claude --models claude-sonnet-4-6 --cases all --stamp base
```

### Codex
前置：装好 `codex` CLI；搭一个 **Responses 兼容网关**（LiteLLM 开 `/responses`），
把本机模型转出去；`export LOCAL_LLM_KEY=<网关key>`。

```bash
cd claude_code
mkdir -p settings/codex
cp settings.example/codex/config.toml.example settings/codex/config.toml
# 编辑 settings/codex/config.toml：base_url 指向你的 Responses 网关、env_key 名对上你 export 的变量
python3 run_eval.py --runner codex --models qwen-agentworld --cases all --stamp cx
```
运行时 `CODEX_HOME` 会被指到 `settings/codex`；模型用 `-m <model>` 逐次覆盖，供应商取 config 里的默认 `model_provider`。

> LiteLLM 开 Responses 面的最小示例（本仓库不含配置）：在 litellm_config 里给目标模型配好后，
> 确认 `POST /v1/responses` 可用；也可用 OpenRouter 等本身提供 Responses 面的路由。

### Hermes
前置：装好 `hermes` CLI；模型上下文 **≥ 64k**。

```bash
cd claude_code
mkdir -p settings/hermes
cp settings.example/hermes/config.yaml.example settings/hermes/config.yaml
# 编辑 settings/hermes/config.yaml：base_url 指向本机 llama-swap :12345、provider=custom
python3 run_eval.py --runner hermes --models custom/qwen-agentworld --cases all --stamp hm
```
运行时会用 bwrap 把 `settings/hermes` 绑成 `~/.hermes`，于是这份配置生效。`--models` 传 `provider/model`。

结果统一写到 `claude_code/results/results_<runner>_<stamp>.json`（文件名带 runner，三套互不覆盖）。

---

## 四、已知限制与影响

1. **Hermes 工具轨迹不可靠**：`hermes -z` 只吐最终文本。工具列表靠事后
   `hermes sessions export` 导出 JSONL 再解析，且其字段形状需实机核实。采不到时驱动会置
   `tools_unknown=True`，`run_eval` 会在该次结果 `detail` 前加「[工具轨迹未采集,需人工复核]」，
   **绝不把「没采到」静默当成「没调工具」**。
   - 受影响的判分：**A1**（要求「常识题不调工具」）依赖工具数为 0；Hermes 上该项须人工复核。
   - 其余用例判分看的是**文件产物 / 最终文本 / git 改动**，不依赖工具数，正常可用。

2. **Codex 需要 Responses 网关**：没有网关就跑不了本地模型（见第二节）。这是部署问题，不是脚本问题。

3. **bwrap 额外绑定**：codex/hermes 可能往各自 home 之外的位置写缓存。目前只暴露了
   `CODEX_HOME` / `~/.hermes` + sandbox + `/tmp`。若实测报「只读文件系统」错，按提示在
   `runners.py` 对应驱动里补一条 `--bind`。

4. **Hermes 的 `worktree.enabled` 键名**是按文档推测写的，实机请对照 `cli-config.yaml.example` 校正，
   确保它**不**另建 git worktree（否则判分读不到模型改动）。

---

## 五、合并前验证清单（本机务必逐项实测）

- [ ] `codex exec --json` 的事件里，最终答复确实来自 `item.completed` 且 `item.type=="agent_message"` 的 `text`；
      工具事件类型名与 `runners.py::CodexRunner` 里解析的一致（`command_execution`/`file_change`/`mcp_tool_call`）。
- [ ] `codex exec -m <model>` 能正确落到 `config.toml` 的默认 `model_provider`；`--skip-git-repo-check`
      与 `--dangerously-bypass-approvals-and-sandbox` 均被接受、且 Codex 自带沙箱确实关闭（能写 sandbox）。
- [ ] LiteLLM（或其它网关）的 `/responses` 面对本地模型可用，Codex 握手成功。
- [ ] `hermes -z "<prompt>" --yolo -m provider/model` 能无人值守跑完、只输出最终文本、且**真的改了 sandbox 文件**。
- [ ] `hermes sessions export <out.jsonl>` 能导出最近会话，其 JSONL 里工具调用字段与
      `runners.py::HermesRunner._collect_tools` 的兜底解析对得上（对不上就照实际字段改）。
- [ ] bwrap 把 `settings/hermes` 绑成 `~/.hermes` 后，Hermes 确实读到了我们的 `config.yaml`（模型/端点正确）。
- [ ] 三个外壳各随便跑一两个用例（如 `--cases A3,C2`），确认 `results_<runner>_*.json` 结构正常、判分合理。

实测跑通、看到真实输出后，再把本节勾掉、更新本文，并考虑把用法折进主 README。
