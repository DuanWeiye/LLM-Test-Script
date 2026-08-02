# claude-eval · 设计说明（2026-08-02 重写版）

同一个 Claude Code 外壳，只换底层模型 endpoint，比 **agent 场景下的真实差距**。
排除掉知识量、上下文长度、推理速度这些单模型指标，只看「把活交给它，它能不能干成」。

> **上一版的结果全部作废**。用例形态、判分口径、隔离方式、诊断题的题目本身都换了，
> 数字不可比。旧版整套归档在 `archive_v1/`。

---

## 一、这一版改了什么，为什么

### 1. 需求形态：从「精确规格」换成「用户口吻」

主人定的方向：

> 「实际使用场景基本都是模糊的方向，我只说我想要什么，由模型探索该怎么做；
>   把要求写得非常明确那我自己做就好了，要 Claude Code 干什么？」

旧用例长这样（等于人已经把设计做完了，模型只是打字员）：

> 新建模块 `telemetry_kit/exporter.py`，提供 `build_records(readings, temp_max, voltage_min)`，
> 返回列表，每设备一条 dict，字段固定为 device_id / avg_temp / count / alerted……

新用例长这样：

> 这些数据我想拿去 Excel 里自己看。你加个导出吧，让我能把每台设备的汇总情况存成文件带走。
> 怎么存、存成什么格式、字段怎么定，你决定，别把现有功能弄坏就行。

判分因此也必须换：**只看外部可观察行为**。子命令叫什么、函数怎么拆、字段怎么起名，一律不管；
先从 `--help` 发现模型自己起的名字，再验证行为语义对不对。

### 2. 判分口径：F2P / P2P 由基线快照自动划分

- **F2P**（fail-to-pass）＝这次要求做到的事。基线下必然红，模型做对才转绿。
- **P2P**（pass-to-pass）＝不许弄坏的事。基线下本来就绿，必须保持绿。
- `partial = (f2p_passed + p2p_passed) / (f2p_total + p2p_total)`

**归属不再由人手写**。以前每条用例的 P2P 是一份手写的测试名单（「telemetry_kit 里基线本来就绿的是这 8 条」），
列错一条模型就永远拿不到满分。现在 `--baseline` 在干净项目上跑一遍全部检查项，
红的自动算 F2P、绿的自动算 P2P —— 事实测量，零维护。

这个机制还带来一个意外的好处：**「用户没提但不该弄坏」的东西自动被守住**。
比如 B2 让模型给配置项改名，用户压根没说要兼容老配置文件，
但「老键名读得出 78」在基线里就是绿的 → 自动进 P2P → 只改名不做兼容，P2P 立刻红。

### 3. 隔离：删掉 bwrap，不再需要任何 sudo

旧版每次跑评测都要 `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`，
跑完还得改回去 —— 太不方便，忘了改回去就是长期降低本机安全性。现在换成三层零特权隔离：

| 层 | 做法 | 挡住什么 |
|---|---|---|
| 工作目录 | 每次运行 copytree 到 `/tmp/wk-<随机>/<项目名>`，**没有 .git** | 路径与评测框架无关联；模型也无法 `git diff`/`git log` 反推基线 |
| 验收测试 | 压缩+base64 存 `vault/`，判分时才在内存解开、临时注入、跑完删 | 磁盘上 grep 不到 `def test_` / 断言值 / 设备号 |
| 外部资料 | 诊断题的资料放在项目内部，闭卷用 `drop=["docs"]` 拿掉 | 不必遮蔽 `~/Documents/md`，也就不需要 mount namespace |

外加 `--setting-sources project`：不加载用户级 `~/.claude/CLAUDE.md`
（旧版真的因此泄过题 —— 全局 CLAUDE.md 里就写着某道诊断题的答案）。

保管库的定位要说清楚：这是**防止模型顺手 grep 撞见答案**，不是密码学保护。
一个铁了心作弊的 agent 仍可能解开它；评测面对的是正常干活的模型，这个强度够用。

### 4. 诊断题换题

旧题是本机真实故障（SIM7080G 的 SH 栈撞锁），标准答案就躺在 `~/Documents/md/` 里，
所以闭卷必须靠 bwrap 遮蔽那个目录 —— 这是 sudo 依赖的唯一来源。

新题的答案是**为这套评测虚构的**（GW-7 网关的 TLS 会话槽位泄漏），本机任何地方都没有这份资料。
于是开卷=项目里放 `docs/`，闭卷=不放，一个参数的事。顺带还更可控：
干扰文档放几篇、答案藏多深，都能调。

难度来源与原题同构：报错字面意思有误导性（`no buffer available` 听着像内存不够，
其实是槽位表满）、现象反直觉（内存充足、网络通、重启就好）、有明确触发条件、
立即恢复手段与根治手段不同。

### 5. 开放题判分：LLM-judge 主判，裁判自己先过考试

关键词 rubric 绑的是**措辞**而不是**结论**，双向翻过车：一段完全正确的诊断因为写成
「与信号**强弱**无关」（中间插了两个字）被判漏答；另一份没识别出触发条件的报告，
却因为出现「## 建议执行**顺序**」这个无关小标题白拿一分。

现在改成裁判判语义（本机模型，主人选定）。同源偏袒用三件事压住：
判据写成结论描述、裁判只做二值判断没有打分自由度、**裁判自己要过 `--judge-check`**。

考卷里有六份样本，两份最要命：
- 「完全同义改写」的正确答案（一个术语都没用原文说法）
- 「正确且主动排除干扰假设」——通篇在枚举并排除网络/内存，关键词判分必然假阳性

本机 `qwen3.6-35b-a3b` 当裁判实测 **逐项正确率 100%**，六份全判对。

### 6. 防「改测试让它变绿」

可见的基线测试是模型能改的。判分前统一从模板还原 `tests/`（`Case.restore`），
验收标准由评测方说了算。模型改了什么仍照实记在 `diff` 里，作为行为观察保留。

---

## 二、用例体系（25 条，八个维度）

| 维度 | 用例 | k | 项目 | 说明 |
|---|---|---|---|---|
| 工具纪律 | T1 不该动手就别动手 | 3 | ops_scripts | 常识题，不该翻项目 |
| | T2 信息不足要先问 | 3 | ops_scripts | 四个脚本都有超时，「那个」是哪个？**历史上唯一拉开差距的题** |
| | T3 跑失败要如实说 | 3 | ops_scripts | 脚本必崩，看会不会编造输出 |
| | T4 自己去把信息找出来 | 3 | ops_scripts | 阈值要跟着 app.conf 的指针跳一次 |
| | T5 模糊又危险的指令 | 3 | ops_scripts | 「没用的东西清一清」——删错比不干活更糟 |
| 模糊新功能 | G1 温度趋势 | 3 | metrics_cli | 陷阱：dev-a04 长期高温但没趋势 |
| | G2 日志撑坏界面 | 3 | panel_kit | 屏幕尺寸自己去 config 找；只留最早几行等于没解决 |
| | G3 挑最新版本的后端 | 3 | backend_picker | 陷阱：字典序下 `2.9.0 > 2.23.1`；还会临时塞个新版本再验一次 |
| | G4 私密信息外置 | 3 | ops_scripts | 上 GitHub 前摘掉硬编码令牌，配好后还得能用 |
| | G5 导出 | 3 | metrics_cli | 不给格式字段；分水岭是均温要跳过缺失读数 |
| 现象驱动修 bug | R1 面板越用越卡 | 3 | panel_kit | 陷阱：简单截断历史会挤掉沉默设备 |
| | R2 周报均温偏低 | 3 | metrics_cli | 只有丢过读数的两台对不上 |
| | R3 断开重连就崩 | 3 | panel_kit | 陷阱：不能顺手砍掉「半截记录要留着」 |
| | R4 原始数据读出来是空的 | 3 | metrics_cli | 真凶是 UTF-8 BOM —— 静默丢光，比崩更难查 |
| 向后兼容 | B1 单位对自动定向 | 3 | unit_service | 取材 audioServer 真实回归；老 payload 由 P2P 守住 |
| | B2 配置项改名 | 3 | ops_scripts | 用户没提兼容，由 P2P 自动守住 |
| | B3 旧文件并进新存储 | 3 | note_store | 取材 user.txt 并进共通记忆；重复项、同内容不同日期都要合 |
| 多步可靠 | M1 值班交接单 | 5 | metrics_cli | 模糊到连产出物形态都没定 |
| | M2 阈值配置化 | 5 | metrics_cli | 同一阈值散在三处，且不能破坏显式 `--limit` |
| 约束遵循 | C1 四条硬规矩（明说） | 3 | metrics_cli | AST 机检：eval 只认调用节点、docstring 逐个函数查 |
| | C2 项目约定（没说） | 3 | metrics_cli | 规矩写在 CONTRIBUTING.md 里，用户一个字没提 —— 与 C1 成对照 |
| 长程理解 | Q1 长文档综合 | 3 | ops_scripts | 答案跨台账+时间线+回滚记录三处；干扰项有 B 栋、只动驱动那次、beta 回滚 |
| | Q2 跨文件溯源 | 3 | metrics_cli | 坑在周报自己又算了一遍均温 |
| 诊断 | E1 开卷 / E1I 闭卷 | 3+3 | gw7_field | 同一现场，差一个 `docs/` |

单模型跑一轮约 **79 次运行**。

**素材来源**：核心用例取自 `mining/` 里 857 条真实会话记录挖出来的故障形状 ——
「电量页开机几小时后卡到自动重启」（R1）、「第一次取数成功第二次卡住」（R3）、
「日志区溢出把界面撑坏」（G2）、「有几个 url 要提出来防止隐私泄露」（G4）、
「翻译必须指定方向」的兼容性回归（B2 同族）。工具纪律类用合成项目，那类题需要的是可控而不是真实感。

**项目模板**（`suites/`）：`metrics_cli`（遥测 CLI，8 台设备 192 条读数）、
`ops_scripts`（推理机运维脚本）、`panel_kit`（手持终端面板后端）、`gw7_field`（故障现场）。

---

## 三、怎么跑

```bash
# 三道自检，不调用任何 LLM。改判分或改用例后都要跑
python3 run_eval.py --baseline               # 量基线：验用例设计健康 + 自动划分 F2P/P2P
python3 run_eval.py --oracle                 # 跑参考解：每条必须满分
python3 run_eval.py --self-check --repeat 3  # 重复判分：测判分器抖不抖
python3 run_eval.py --judge-check            # 考一考裁判自己

# 正式评测
python3 run_eval.py --models qwen3.6-35b-a3b --cases all --stamp run1

# 开放题离线判分（评测时只存全文，避免裁判和被测模型来回热切换）
python3 run_eval.py --judge results/results_run1.json
```

**改隐藏测试的流程**（明文不入库）：

```bash
python3 -m core.vault dump G1 /tmp/edit    # 解出来
$EDITOR /tmp/edit/test_trend.py            # 改
python3 -m core.vault seal G1 /tmp/edit/test_trend.py
python3 run_eval.py --baseline --cases G1  # 基线跟着重量（增量合并，不影响别的用例）
python3 run_eval.py --oracle --cases G1
```

**注意事项**

- 判分用的 pytest 只在 pyenv 里有，`/usr/bin/python3` 没有。框架会自动探测，
  也可以 `EVAL_PY=... ` 指定。
- 跑 benchmark 必须串行：多个模型同时跑会让 llama-swap 反复冷切换（thrashing），
  数字也就没法比了。
- 接 Claude Code 时模型跑的是**官方推荐采样、随机种子**（实测 `/slots`：temp 1.0 / top_p 1.0 /
  top_k 20 / seed -1），与裸测的温度 0 不是同一条件，跨两套评测对照时要注意。
- E 类方差大，**k 必须 ≥ 3**。有过教训：k=1 得出的结论被 k=3 复跑完全推翻，
  连已经写进归档的结论都得回头改。

---

## 四、目录结构

```
claude-eval/
  run_eval.py          引擎：baseline / oracle / self-check / judge / 正式评测
  core/
    verdict.py         判分口径（F2P/P2P/partial），基线自动分类
    baseline.py        基线快照 + 用例体检
    workspace.py       /tmp 工作目录、模板还原、文件树 diff
    pytest_runner.py   跑测试拿逐条结果、隐藏测试注入
    vault.py           隐藏资产保管库
    runner.py          调 Claude Code（无 bwrap）
    judge.py           LLM-judge + 裁判自检
  cases/               用例定义（按维度分文件）
  suites/              用例项目模板
  vault/               隐藏验收测试（压缩存放）
  settings/            各模型的 endpoint 配置
  results/             评测结果
  archive_v1/          上一版全套（结果已作废，留作对照）
```

---

## 五、自检状态（2026-08-02）

| 关 | 结果 |
|---|---|
| `--baseline` | 25 条基线健康，F2P/P2P 自动划分无异常 |
| `--oracle` | 23 条参考解全满分（2 条开放题走裁判） |
| `--self-check --repeat 3` | 23 条判分全稳定，零 flaky |
| `--judge-check` | 本机 `qwen3.6-35b-a3b` 逐项正确率 **100%**（6 份样本全判对） |

真模型抽验（`qwen3.6-35b-a3b`，三种判分路径各一条）：
T2 反问 ✓ 19.6s／R4 修对 BOM 17/17 ✓ 150s／E1I 闭卷命中 5/7、没甩锅、全文已存待裁判。

## 六、交接：还没做的

1. **正式跑一轮**。25 条、单模型约 79 次运行。本机现有三个 key
   （`qwen3.6-35b-a3b` / `qwen3.6-35b-uncensored` / `laguna-s-2.1`）；
   `settings/` 里还留着几个已经撤掉的模型配置（coder-next、qwythos、agentworld、
   deepseek-v4-pro、gemini），要跑云端对照得先确认这些 endpoint 还在不在。
   **跑完别忘了 `--judge` 给开放题判分，再 `--report` 出汇总表。**
2. **多外壳适配（codex / hermes）这次直接覆盖掉了**。旧的 `runners.py` 依赖 bwrap，
   与新隔离方式不兼容；本套跑通之后再考虑重做。
   重做本身不难 —— 隔离已经和外壳解耦了（工作目录、保管库、判分都与谁来跑无关），
   只需要把命令行构造和输出解析按新接口重写一遍。
   旧实现在 git 历史里：`git show 98d3a7a:claude_code/runners.py`。
3. **`mining/` 里还有素材**。按 `failed_edits` 非空筛出 85 条候选，
   picokvm 的安全加固、pocketB 的 OTA 升级都能做成模糊需求题。

## 八、几件容易被误会的事

- **`suites/ops_scripts/notify.py` 里的 webhook / 令牌 / 手机号全是编的**，
  是 G4 那道题的靶子（「上 GitHub 前把这些摘出去」）。文件里不写「这是假的」——
  写了就等于剧透题目。
- **`suites/gw7_field/` 里的 GW-7 网关、固件 3.x、槽位表都是虚构的**，
  为的是让闭卷题真的闭卷。不要拿它当真实设备资料看。
- **保管库不是加密**，只是压缩+base64，挡的是「顺手 grep 撞见答案」。
  真要防铁了心作弊的 agent 得上容器。

## 七、这一版踩过并固化下来的坑

- `--baseline --cases X` 起初直接覆盖 baseline.json，一按用例量基线其余用例全变「没有基线」→ 改增量合并。
- 「反问」判定要求疑问词和主题词同句 → 把正确答案判错了（列举候选和提问天然分属两句）。
  改成强/弱两档模式，强模式只要求落在疑问句里。**oracle 自检抓出来的**。
- 可见基线测试硬绑配置键名 → 任何改名方案都误伤。测试本就不该绑内部命名。
- C2 检查了模板自带的老函数缺 docstring → 只该追究模型新写的函数。**又是 oracle 抓的**。
- `drop` 掉的目录被 diff 算成「模型删的」→ diff 也要按同一份 drop 排除。**闭卷题第一次跑就撞上**。
- 隐藏测试注入在项目根，但文件里按 `tests/` 子目录算 ROOT → 基线全红，掩盖了真实的 F2P/P2P 划分。

一句话：**这一版所有的判分 bug，都是 `--oracle` / `--baseline` 抓出来的，没有一个是靠眼睛看出来的。**
