#!/usr/bin/env python3
"""Stock-only entry point. Use start.sh for environment and process isolation."""
import argparse
import asyncio
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check_profile():
    from stock_profile import validate_stock_profile
    validate_stock_profile(ROOT)
    print('Stock profile valid: five stocks, dedicated runtime, hard nominal/margin limits')


async def live():
    from stock_runtime import load_stock_environment, StockOrchestrator
    check_profile()
    load_stock_environment()
    orc = StockOrchestrator()
    try:
        await orc.start()
        await asyncio.Event().wait()
    finally:
        await orc.stop()


def main():
    if os.environ.get('STOCK_LAUNCHER_ROOT') != str(ROOT) or Path.cwd().resolve() != ROOT:
        raise SystemExit('Use ./start.sh monitor|check|live')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('check', 'live'))
    args = parser.parse_args()
    check_profile()
    if args.mode == 'live':
        asyncio.run(live())


if __name__ == '__main__':
    main()
