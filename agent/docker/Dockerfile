# 评测容器：被测模型在这里面干活。
#
# 为什么要有它（2026-09-06 事故之后）：chmod / bwrap 两档写屏障都是「仓库在那儿、
# 但拦着不让动」。容器换了个思路 —— **仓库压根不存在于这个文件系统里**，
# 同 UID 的模型 chmod 不回来，也读不到答案册。顺带把泄题通道从「靠环境变量挡」
# 变成「宿主的 ~/.claude/CLAUDE.md、祖先 AGENTS.md 在容器里根本不存在」。
#
# ★ 镜像内容＝评测条件的一部分：模型手上有哪些工具、python/node 是什么版本，
#   从「本机 PATH 的偶然」变成这份 Dockerfile 里钉死的东西。改版本＝换口径，
#   要像换模板一样当作一次口径变更记进报告。
FROM python:3.12-slim

# node 跟宿主 vendor/ 里跑通过的那个大版本对齐（宿主 v24.14.1）。
# 交接草案里写的是 node 22，但宿主实测跑通的是 24 —— 用 22 等于引入一个没验证过的变量。
ARG NODE_VERSION=24.14.1
# opencode 钉死版本：外壳版本变了，agent 卷的成绩就不可横比。
ARG OPENCODE_VERSION=1.18.29
# pytest 对齐宿主判分侧（pyenv 3.12.11 + pytest 9.1.1）：模型在容器里自测的结果
# 与宿主判分跑出来的结果口径一致，免得「模型说通过了、判分说没过」。
ARG PYTEST_VERSION=9.1.1
ARG NUMPY_VERSION=2.4.4
ARG PANDAS_VERSION=3.0.2
ARG REQUESTS_VERSION=2.33.1

# 模型干活要用的基本工具。ripgrep 是 opencode 内置 grep 工具的后端，缺了它搜不动。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ripgrep curl ca-certificates xz-utils procps less \
    && rm -rf /var/lib/apt/lists/*

# node 官方 arm64 二进制（本机是 DGX Spark / aarch64）
RUN set -eux; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-arm64.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1; \
    node --version

# 除 pytest 外这几个是给**裸卷代码执行档**用的（run_code / run_code_verdict 也进容器跑）。
# 模型写的解答里真的出现过 numpy/pandas —— 容器里缺一个库，判分就会把「宿主上跑得通的
# 答案」记成「代码不可用」，那是口径漂移，不是模型退步。版本对齐宿主 pyenv 3.12.11。
# scipy/torch 这类没跟：算法题用不上，跟了镜像要大一个量级。真遇到就补进这一行。
RUN pip install --no-cache-dir \
        "pytest==${PYTEST_VERSION}" \
        "numpy==${NUMPY_VERSION}" \
        "pandas==${PANDAS_VERSION}" \
        "requests==${REQUESTS_VERSION}"

# opencode 装在镜像里，**不挂宿主 vendor/**：宿主那份按 Ubuntu 24.04 的 glibc 2.39 装，
# 塞进 Debian 基础镜像大概率起不来。
RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" && opencode --version

# 容器以 --user <宿主uid>:<宿主gid> 跑（产出文件属主必须是主人，宿主判分要读文件树 diff），
# 这个 uid 在镜像的 /etc/passwd 里没有条目，git 会因为「查不到当前用户」直接罢工。
# 给一份全局 gitconfig 兜底：用例里模型要 git commit 时不至于卡在这种环境细节上。
COPY gitconfig /etc/gitconfig
RUN git config --system --list

# 默认不进 shell：runner.py 每次显式给完整命令。
CMD ["opencode", "--version"]
