#!/usr/bin/env bash
# 初始化 sandbox 为 git 基线。
# run_eval.py 每个用例跑前会在 sandbox 里 `git reset --hard` + `git clean` 还原，
# 所以 sandbox 必须先是一个已提交的 git 仓库。首次使用前跑一次本脚本即可。
set -euo pipefail
cd "$(dirname "$0")/sandbox"
if [ -d .git ]; then
  echo "· sandbox 已是 git 仓库，跳过 init"
else
  git init -q
fi
git add -A
git commit -qm "sandbox baseline" || echo "· 无改动可提交（已是最新基线）"
echo "✓ sandbox git 基线就绪：$(pwd)"
