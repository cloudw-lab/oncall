#!/usr/bin/env zsh
# 通过 Prometheus remote_write 写入示例指标（demo_oncall_*）
# 用法：./write_demo_metrics.sh [批次数]

set -euo pipefail

BATCHES="${1:-5}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 "$SCRIPT_DIR/write_demo_metrics_remote.py" --batches "$BATCHES"

