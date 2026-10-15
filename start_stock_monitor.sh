#!/bin/sh
set -eu
[ "$#" -eq 0 ] || { echo "Usage: ./start_stock_monitor.sh (public only; live is unavailable through this alias)" >&2; exit 2; }
STOCK_PYTHON=${STOCK_MONITOR_PYTHON:-${STOCK_PYTHON:-$(command -v python3)}}
export STOCK_PYTHON
exec "$(dirname -- "$0")/start.sh" monitor
