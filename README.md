# Lighter–Arcus Stock Spread Monitor

A terminal monitor for public stock perpetual quotes on Lighter and Arcus. The supplied profile tracks **MU, SNDK, NVDA, AMD, and INTC**. SPCX is unsupported and rejected by the public profile validator.

The supported launcher always selects `--public-only`. This mode uses empty authentication, does not read account credentials or account state, does not create a signer or trading executor, and does not submit or cancel orders. Other legacy modules are included because the existing Python packages import them; only the public launcher described here is supported by this snapshot.

## Install and run

Use Python **3.12** on macOS or Linux, with a terminal and access to the exchanges' public HTTPS and WebSocket endpoints. The launcher requires Unix `fcntl` file locking.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lighter-arcus.txt
export STOCK_MONITOR_PYTHON="$(pwd)/.venv/bin/python"
./start_stock_monitor.sh
```

`STOCK_MONITOR_PYTHON` must be an absolute executable path. Run the launcher without arguments; `live` and all other arguments are rejected. Stop the foreground process with Ctrl+C. A local file lock prevents a second copy from running in the same checkout.

The launcher clears inherited environment variables, including credentials, proxy settings and `PYTHONPATH`, before starting Python. It uses the included `config/arbitrage/stock_monitor.yaml` and `config/symbol_conversion.yaml`; do not add account configuration, API keys, signing keys, or an `.env` file.

## Reading the monitor

The profile screens for a **0.30% gross spread** between the buy venue's best ask and the sell venue's best bid, in both directions. This is a quote difference, not profit or an executable arbitrage signal. Fees, funding, slippage, liquidity, latency and execution risk can erase the displayed spread.

Empty, one-sided, crossed, non-finite, non-positive or stale order books suppress opportunities until valid quotes recover. Startup requires every configured stock market to be active on both venues. Listings, access policies, market hours and data availability can change; stock perpetuals are exchange products and are not direct ownership of shares.

## Connections and local data

Public Lighter WebSocket connections use the official `readonly=true` endpoint. Both public WebSocket adapters explicitly set `proxy=None` and do not discover system proxies. Public Lighter HTTPS and WebSocket clients enforce TLS certificate verification; an inherited setting cannot disable it. A network that requires a proxy may therefore fail to connect.

The monitor creates local `logs/`, `data/` and `run/` directories. The supplied profile records spread history under `data/stock_spread_history`. Public quote requests disclose ordinary connection metadata to exchange services; local logs and history should be reviewed before sharing. Generated runtime files and credential paths are ignored by Git, but ignore rules do not inspect file contents or guarantee that a file is safe to publish.

## Offline checks

Install the test runner separately, then run the supplied stock and public-mode contracts from the repository root:

```sh
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q tests/test_arcus_adapter.py tests/test_arcus_lighter_live_guards.py
```

These checks use fake transports and fixed offline sentinels. They exercise public configuration validation, symbol conversion, missing and malformed data, reconnect settings, TLS, absence of account reads and writes, launcher argument rejection, environment isolation and duplicate locking. They do not validate a live exchange connection, real market availability or trading profitability.

## License and attribution

The source snapshot supplied for this release did not include a license file or an explicit license grant. This release adds no license terms. Existing third-party attribution and copyright markers remain in the included source; dependencies retain their respective licenses.
