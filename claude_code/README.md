# claude-eval

同一个 Claude Code 外壳，只换底层模型 endpoint，比 **agent 场景下的真实差距**。

设计说明、用例清单、判分口径、踩过的坑都在 **[DESIGN.md](DESIGN.md)**，接手先读那个。

## 跑一轮的完整流程

```bash
cd ~/Documents/dgx/claude-eval

# 1) 跑前先过自检（前两步不花 LLM，几分钟）——确认框架本身是好的
python3 run_eval.py --baseline               # 量基线 + 用例设计体检
python3 run_eval.py --oracle                 # 参考解必须条条满分
python3 run_eval.py --judge-check            # 裁判自己先过考试（这步会调本机模型）

# 2) 正式评测（25 条用例，单模型约 79 次运行；**必须串行**，别同时跑多个模型）
python3 run_eval.py --models qwen3.6-35b-a3b --cases all --stamp run1

# 3) 给两条开放题（诊断类）判分 —— 评测阶段只存了全文，判分单独跑
python3 run_eval.py --judge results/results_run1.json

# 4) 出汇总表
python3 run_eval.py --report results/results_run1.json
#    多个模型分批跑的话，把结果文件都列上即可：
#    python3 run_eval.py --report results/results_run1.json results/results_run2.json
```

**不需要任何 sudo / sysctl。** 隔离靠「/tmp 中性工作目录 + 验收测试存保管库 +
`--setting-sources project`」三层。

### 报告怎么读

格子是 `pass@1 (partial 均值)`：

- **pass@1** 是全或无口径 —— F2P 全过、且 P2P 一条没坏，才算过。
- **partial** 是细粒度 —— 在「大家都满分」的饱和区里仍然能区分模型。
- **⚠** 表示有运行被中断（超时／空输出），**❗** 表示判分器自己出错。
  这两种都**不是**「模型答错」，看到了要单独查一眼。

想看某次具体干了什么：结果 json 里每次运行都存了 `tools`（调过哪些工具）、
`changed`（动了哪些文件）、`result_head`（输出开头 800 字），开放题另存 `result_full` 全文。

## 改了判分或用例之后

三关必须重跑，缺一不可：

```bash
python3 run_eval.py --baseline --cases <改动的用例>   # 基线跟着重量（增量合并，不影响别的）
python3 run_eval.py --oracle   --cases <改动的用例>   # 参考解还得满分
python3 run_eval.py --self-check --repeat 3           # 判分不能抖
```

**这一版所有的判分 bug 都是这三关抓出来的，没有一个是靠眼睛看出来的。**

## 加一条用例

1. 在 `suites/` 下放一个项目模板 —— **可见测试必须基线全绿**
   （基线里有红测试，等于模型一进门就被剧透了要改哪儿）
2. 写隐藏验收测试，`python3 -m core.vault seal <用例ID> <文件>` 封存；
   要改的时候 `python3 -m core.vault dump <用例ID> /tmp/edit` 解出来，改完再封回去
3. 在 `cases/<维度>.py` 里加一条 `Case`，配上参考解 `oracle`
4. 三关跑通才算能用

隐藏测试是注入在**项目根**的，所以文件里写 `ROOT = Path(__file__).resolve().parent`。

## 目录

```
run_eval.py   引擎：baseline / oracle / self-check / judge / report / 正式评测
core/         判分口径、基线快照、工作目录、保管库、裁判
cases/        用例定义（按维度分文件）
suites/       用例项目模板
vault/        隐藏验收测试（压缩存放，grep 不到）
settings/     各模型的 endpoint 配置（含 key，不入库）
archive_v1/   上一版（bwrap 隔离 + 精确需求形态），结果已作废，留作对照
```
