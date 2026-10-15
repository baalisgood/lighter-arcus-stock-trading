#!/bin/sh
# Foreground, public-only process. No trading/account flags are accepted.
set -eu
if [ "$#" -ne 0 ]; then
    echo 'Usage: ./start_stock_monitor.sh (public monitoring only; live is unavailable)' >&2
    exit 2
fi
STOCK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$STOCK_ROOT"
STOCK_PYTHON=${STOCK_MONITOR_PYTHON:-$(command -v python3)}
case "$STOCK_PYTHON" in
    /*) ;;
    *) echo 'STOCK_MONITOR_PYTHON must be an absolute Python executable path' >&2; exit 2 ;;
esac
exec /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" TERM="${TERM:-dumb}" LANG="${LANG:-en_US.UTF-8}" PYTHONDONTWRITEBYTECODE=1 "$STOCK_PYTHON" - "$STOCK_ROOT" <<'PY'
import fcntl
import os
from pathlib import Path
import runpy
import sys

root = Path(sys.argv[1]).resolve()
os.chdir(root)
run_dir = root / 'run'
run_dir.mkdir(exist_ok=True)
if not run_dir.resolve().is_relative_to(root):
    raise SystemExit('Stock run directory escapes project')
# Keep this descriptor alive throughout runpy; kernel releases the lock on exit.
lock_fd = os.open(run_dir / 'stock_monitor.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Stock monitor is already running')
for name in ('logs', 'data'):
    if not (root / name).resolve().is_relative_to(root):
        raise SystemExit(f'Stock {name} directory escapes project')
sys.path.insert(0, str(root))
sys.argv = [str(root / 'run_arbitrage_monitor_v2.py'), '--public-only',
            '--config', str(root / 'config/arbitrage/stock_monitor.yaml')]
runpy.run_path(sys.argv[0], run_name='__main__')
PY
