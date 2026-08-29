#!/usr/bin/env bash
# MOM 策略一键跑：生成信号表 → 端到端回测（Input → Engine → Analyzer → Visualizer）
#
# 后台运行（推荐，全量面板计算耗时，勿在前台阻塞）：
#     nohup bash examples/mom/run.sh > /dev/null 2>&1 &
#     tail -f examples/mom/logs/run_mom.log
#
# 信号已生成时可跳过第一步：SKIP_BUILD=1 bash examples/mom/run.sh
set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HERE/logs"
LOG="$LOG_DIR/run_mom.log"
mkdir -p "$LOG_DIR"

# 全程严格在 myenv 中执行
source /home/MZYang_tmp/anaconda3/etc/profile.d/conda.sh
conda activate myenv

{
  echo "==== $(date '+%F %T') MOM 开始 | python=$(which python) ===="
  if [ "${SKIP_BUILD:-0}" = "1" ]; then
    echo "---- 跳过信号生成（SKIP_BUILD=1）----"
  else
    echo "---- 步骤 1/2：生成信号表 ----"
    python "$HERE/build_signal.py"
  fi
  echo "---- 步骤 2/2：端到端回测 ----"
  python "$HERE/run_backtest.py"
  echo "==== $(date '+%F %T') MOM 完成 ===="
} > "$LOG" 2>&1
