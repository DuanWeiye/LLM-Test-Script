# LLM Test Script

一套**本地大模型能力评测脚本**，用两个互补的视角考同一批模型：

| 目录 | 名字 | 考什么 | 怎么接模型 |
|---|---|---|---|
| [`bare_llm/`](bare_llm/) | **纯裸测** | 模型**自己会什么**。分两档：**主卷**＝高难算法 / 工具判断 / 多约束指令 / 多轮一致性 / 长上下文推理 / 约束冲突（选型看这个）；**回归卷**＝已饱和的基本功，只用来发现退步 | 直连任意 **OpenAI 兼容** `/chat/completions` 端点 |
| [`agent/`](agent/) | **接 agent 外壳** | **把活交给它能不能干成**：25 条用户口吻的模糊需求，只测外部可观察行为 —— 多轮工具编排、改代码跑隐藏验收、缺参反问、开卷/闭卷诊断 | 用 opencode 当统一外壳，只换底层模型 endpoint |

两套用**同一批模型**跑，才能看出「裸模型能力」和「装进 agent 外壳后的实战表现」的差异 ——
很多模型在裸测某个维度弱，在有完整脚手架的 agent 环境里并不复现，反之亦然。

> 起源：在一台 NVIDIA DGX Spark（GB10 / ARM64）上评测本地部署的多个 Qwen 系模型
> （经 llama.cpp / llama-swap 提供 OpenAI 兼容端点），顺带对照几个云端模型。
> 脚本本身与具体硬件、具体模型无关，任何 OpenAI 兼容端点都能用。

---

## 快速开始

**前置**：Python 3.10+（裸测只用标准库）、一个 OpenAI 兼容端点、以及 agent 卷所需的
Docker（评测容器，见下）。开放题判分需要一个端点当裁判，可用 `JUDGE_BASE` / `JUDGE_MODEL`
/ `JUDGE_KEY` 覆盖。**本仓库不含任何 key 或代理配置，端点请自行搭建。**

### 纯裸测

```bash
export LLM_BASE_URL="http://你的地址:端口/v1"    # 默认 http://127.0.0.1:12345/v1
cd bare_llm
python3 full_eval.py      "my-model" run1       # 常规卷
python3 full_eval_hard.py "my-model" run1       # 难卷
```

卷制、入卷标准、采样口径与噪声控制见 [`bare_llm/README.md`](bare_llm/README.md)。

### 接 agent 外壳

```bash
# 0) 建评测镜像（模型在容器里干活；只需一次）
cd agent/docker && docker build -t llm-eval-agent:1.18.29 . && cd ../..

# 1) 配 endpoint（settings/ 已被 .gitignore 忽略，真实 key 不会入库）
mkdir -p agent/settings
cp agent/settings.example/local-model.json.example agent/settings/my-model.json
#   编辑：provider 的 baseURL 与模型 id（provider 名必须叫 local）

# 2) 跑前自检（前两步不花 LLM）
cd agent
python3 run_eval.py --baseline      # 量基线 + 用例设计体检
python3 run_eval.py --oracle        # 参考解必须条条满分
python3 run_eval.py --judge-check   # 裁判自己先过考试

# 3) 正式评测（单模型约 79 次运行；**必须串行**，别同时跑多个模型）
python3 run_eval.py --models my-model --cases all --stamp run1

# 4) 开放题离线判分 + 出汇总表
python3 run_eval.py --judge  results/results_run1.json
python3 run_eval.py --report results/results_run1.json
```

报告里的格子是 `pass@1 (partial 均值)`；`⚠` 表示有运行被中断（超时/空输出），
`❗` 表示判分器自己出错 —— 这两种都**不是**「模型答错」，要单独查。

用例体系、判分口径（F2P / P2P 由基线快照自动划分）、怎么加一条用例，
见 [`agent/README.md`](agent/README.md) 与 [`agent/DESIGN.md`](agent/DESIGN.md)。

---

## 隔离与防泄题

评测框架最容易坏在这里：模型读到答案、或者跑出工作目录改坏框架，成绩就全部作废。
这套框架为此有四层，**开跑时会打印当前档位，绝不静默降级**：

| 层 | 做法 | 挡住什么 |
|---|---|---|
| 工作目录 | 每次运行复制到 `/tmp/wk-<随机>/<项目名>`，**没有 .git** | 路径与框架无关联，也无法 `git diff` 反推基线 |
| 写屏障 | **docker**（默认：仓库压根不挂进容器）／ bwrap ／ chmod 三档 | 模型看不见也够不着仓库 —— 答案册、出题源、保管库全部不存在于那个文件系统 |
| 框架指纹 | 每次运行前后对框架树（含 `.git` 的 HEAD/index/refs）算 sha256 | 万一哪天护栏失效，对不上立即中止整轮，不靠人眼发现 |
| 模型写的代码 | 裸卷 `run_code()` 也在容器里跑（`--network none`） | 框架主动执行模型输出的那一步，同样不给宿主权限 |

另外两处与「防泄题」直接相关的设计：

- **验收测试对模型不可见**：压缩+base64 存 `agent/vault/`，判分时才临时注入、跑完删除，
  磁盘上 grep 不到 `def test_` 与断言值。挡的是「顺手 grep 撞见答案」。
- **外壳的规则文件通道全部堵死**：opencode 会加载全局配置、`~/.claude/CLAUDE.md`
  （曾经真的因此泄过题）、以及**祖先目录的 `AGENTS.md`**。前两条靠隔离的配置目录与
  环境变量挡，第三条挡不住 —— 所以跑之前会扫工作目录的父链，发现规则文件直接中止。

细节与踩坑经过见 [`agent/DESIGN.md`](agent/DESIGN.md) 〇之二节。

> ★ **镜像版本＝评测条件的一部分**：`agent/docker/Dockerfile` 里钉死了 opencode / node /
> python / pytest 等版本，也就是「模型手上有哪些工具」。改镜像等于换口径，要像换模板那样
> 记进报告，不能当成纯运维改动。

---

## 评测理念（几条踩过坑的经验）

- **看 `pass^k` 不只看 `pass@1`**：同一道难题重复跑 k 次、k 次全过才算稳。小模型和顶级模型
  最大的差距往往在**一致性**，不在单次对错。
- **判分器自己也要有 oracle**：拿参考解跑一遍，不满分就说明框架坏了、这批模型的分数全部不可信。
  本仓库这一版的**每一个**判分 bug 都是这么抓出来的，没有一个是靠眼睛看出来的。
- **裁判也要过考试**：用 LLM 判开放题之前，先拿标注好的样本考一考它（含同义改写的正确答案、
  以及「提到 X 只为排除 X」这种最容易假阳性的写法），判不对就别用它的结论。
- **关键词判对错必有假阳性**：越彻底的回答越会「主动提到 X 来排除 X」，朴素子串匹配会把
  高级回答误杀（本仓库的诊断判分对「排除语境」做了否定判定，可作参考）。
- **主观题别让被测模型自评**：幻觉诚实度 / 代码质量 / 翻译忠实度这类，脚本只收集产物，
  交人或独立模型盲评。
- **需求写太细就测不出东西**：把字段名、函数名、算法都写进需求，模型只是打字员；真实场景里
  用户只说想要什么，「怎么做」本来就是 agent 该扛的部分。
- **「全灭」第一反应是查判分器**，不是「这题太难」—— 截断、围栏不闭合、判分器退化，
  都会伪装成模型无能。

---

## 题库详解 `CASEBOOK.casebook`（含答案，故意不放明文）

每道题在考什么、题面长什么样、标准答案是什么、判分器凭什么说你对或不对，都在这份里，
外加 F2P / P2P / partial / pass@1 / pass^k / oracle / 保管库 / 开卷闭卷这些概念的通俗解释。

**这是一个加了密码的 zip，密码就写在下面**：

```bash
unzip -P casebook-spoiler-2026 CASEBOOK.casebook                  # 解开来看
# 改完重新打包：
zip -e -P casebook-spoiler-2026 CASEBOOK.zip CASEBOOK.md && mv -f CASEBOOK.zip CASEBOOK.casebook
```

**为什么不直接放 markdown**：明文提交到公开仓库，它就会被爬进各家的预训练语料 ——
以后再用这套题测新模型，模型可能在预训练里就见过答案，而你没有任何办法分辨它是真推理出来的
还是背出来的。公开基准逐渐失去区分度走的就是这条路；本仓库的题全部自出、没搬运任何现成基准，
正是为了避开它。密码公开写在这里，人要看随时能看 —— 挡的是自动化抓取，不是有心人，
和 `vault/` 一个思路。明文的 `CASEBOOK.md` 被 `.gitignore` 忽略，从未进过 git 历史。

---

## 隐私与安全

- 仓库内**不含任何 API key、代理地址或个人配置**：整个 `settings/` 被忽略、只提供
  `settings.example/` 占位；所有脚本的端点均可用环境变量覆盖。
- `suites/` 里的公司 / 设备 / 人名 / 数值 / 日志全是**评测用合成数据**。其中
  `ops_scripts/notify.py` 里的 webhook、令牌、手机号是某道用例的靶子（「上 GitHub 前把
  这些摘出去」），**都是编的**；文件里不加「这是假的」注释，加了就等于剧透题目。

## License

[MIT](LICENSE) © 2026 DuanWeiye
