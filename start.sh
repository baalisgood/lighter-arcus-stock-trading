#!/bin/sh
set -eu
umask 077
[ "$#" -eq 1 ] || { echo 'Usage: ./start.sh monitor|check|live' >&2; exit 2; }
case "$1" in monitor|check|live) ;; *) echo 'Unknown mode' >&2; exit 2;; esac
STOCK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$STOCK_ROOT"
STOCK_PYTHON=${STOCK_PYTHON:-$(command -v python3)}
case "$STOCK_PYTHON" in /*) ;; *) echo 'STOCK_PYTHON must be absolute' >&2; exit 2;; esac
exec /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" TERM="${TERM:-dumb}" LANG="${LANG:-en_US.UTF-8}" PYTHONDONTWRITEBYTECODE=1 STOCK_LAUNCHER_ROOT="$STOCK_ROOT" "$STOCK_PYTHON" - "$STOCK_ROOT" "$1" <<'PY'
import fcntl
import os
from pathlib import Path
import runpy
import sys
root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
os.chdir(root)
for name in ('run', 'logs', 'data', 'config', 'core'):
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise SystemExit(f'Stock {name} directory escapes project')
    if name in ('run', 'logs', 'data'):
        path.mkdir(exist_ok=True)
# Reject nested symlinks before imports or creation of runtime log/data files.
for name in ('config', 'core', 'run', 'logs', 'data'):
    if any(p.is_symlink() for p in (root / name).rglob('*')):
        raise SystemExit('Stock profile refuses symlinked config/code/runtime files')
lock_fd = os.open(root / 'run/stock.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('A stock process is already running')
sys.path.insert(0, str(root))
if mode == 'monitor':
    sys.argv = [str(root / 'run_arbitrage_monitor_v2.py'), '--public-only', '--config', str(root / 'config/arbitrage/stock_monitor.yaml')]
else:
    sys.argv = [str(root / 'run_stock.py'), mode]
runpy.run_path(sys.argv[0], run_name='__main__')
PY
