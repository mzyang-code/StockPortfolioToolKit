#!/usr/bin/env bash
# WSTR 策略一键跑：生成信号表 → 端到端回测（Input → Engine → Analyzer → Visualizer）
#
# 后台运行（推荐，全量面板计算耗时，勿在前台阻塞）：
#     nohup bash examples/wstr/run.sh > /dev/null 2>&1 &
#     tail -f examples/wstr/logs/run_wstr.log
#
# 信号已生成时可跳过第一步：SKIP_BUILD=1 bash examples/wstr/run.sh
set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HERE/logs"
LOG="$LOG_DIR/run_wstr.log"
mkdir -p "$LOG_DIR"

# 全程严格在指定 conda 环境中执行。环境名取 CONDA_ENV，默认 myenv。
# conda.sh 的位置随安装方式而变，按 conda 自身所在的 base 目录推断；
# conda 不在 PATH 中时（如某些 cron / nohup 环境），用 CONDA_SH 显式指定。
CONDA_SH="${CONDA_SH:-$(conda info --base 2>/dev/null)/etc/profile.d/conda.sh}"
if [ ! -f "$CONDA_SH" ]; then
  echo "找不到 conda.sh，请设置 CONDA_SH=<conda 安装目录>/etc/profile.d/conda.sh" >&2
  exit 1
fi
source "$CONDA_SH"
conda activate "${CONDA_ENV:-myenv}"

{
  echo "==== $(date '+%F %T') WSTR 开始 | python=$(which python) ===="
  if [ "${SKIP_BUILD:-0}" = "1" ]; then
    echo "---- 跳过信号生成（SKIP_BUILD=1）----"
  else
    echo "---- 步骤 1/2：生成信号表 ----"
    python "$HERE/build_signal.py"
  fi
  echo "---- 步骤 2/2：端到端回测 ----"
  python "$HERE/run_backtest.py"
  echo "==== $(date '+%F %T') WSTR 完成 ===="
} > "$LOG" 2>&1
