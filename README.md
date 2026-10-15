# Lighter–Arcus stock perpetual arbitrage

MU, SNDK, AMD, NVDA and INTC on the original unified segmented trading engine. Trading decisions, execution, account reconciliation and risk controls use the original code. The stock-specific runtime and hard-coded 1,500 USDC limit have been removed. Stock symbols, quantities and monetary limits are YAML configuration.

## Install and run

Use Python 3.12 on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-lighter-arcus.txt
bash start.sh check
mkdir -p config/exchanges
cp examples/lighter_config.yaml.example config/exchanges/lighter_config.yaml
cp examples/arcus_config.yaml.example config/exchanges/arcus_config.yaml
chmod 600 config/exchanges/*_config.yaml
# Fill the empty authentication fields locally with dedicated stock subaccount credentials.
bash start.sh monitor
# Explicit real trading:
bash start.sh live
```

`check` checks local YAML syntax only, without credentials or network access. Both `monitor` and `live` run the original `main_unified.py`; native monitor mode requires account authentication and queries accounts, but disables strategy order submission. `start_stock_monitor.sh` aliases monitor. `scripts/start_lighter_arcus.sh` defaults to monitor. `STOCK_PYTHON` (or `ARBITRAGE_PYTHON`) can select an absolute interpreter path.

The wrapper clears inherited credentials/environment, uses this directory's `.env` and exchange YAML, refuses symlinked credential paths and shares a local process lock. Optional `.env.example` uses the original variable names; integer fields must be filled or omitted, not left blank in an actual `.env`. Real credential files, runtime data and handoff notes are ignored. Never copy credentials from the currency process. Shutdown follows original engine behavior, including its emergency-close handling; stopping does not guarantee positions are closed.

## Configuration and target

Edit `config/arbitrage/arbitrage_segmented.yaml` for quantities, thresholds and risk limits. `monitor_lighter_arcus.yaml` and `multi_exchange_arbitrage.yaml` select only the five stocks; `arbitrage_lighter_arcus.yaml` configures the original execution modes/fees. `multi_leg_pairs.yaml` and `extra_symbols.yaml` contain no additional symbols.

| Parameter | Default |
| --- | --- |
| Each venue's combined nominal cap | 5,000 USDC |
| Each stock's nominal cap per venue | 1,000 USDC |
| Dynamic cap | Original account total × 1.0 |
| Low balance opening gate | 4,500 USDC account total |
| First net spread threshold | 0.15% |
| Grid step / maximum grids | 0.09 percentage points / 2 |
| Per-leg slippage tolerance | 0.01% |

All monetary values above are configurable; no stock runtime imposes a second monetary ceiling. These are nominal exposure limits, not a guarantee of using all capital, margin requirements or maximum loss. The effective nominal ceiling is the smaller of the static cap and account total × equity_multiplier; raising only the static cap can still leave the dynamic cap binding. Both settings are configurable. Other original account, execution, freshness and persistence guards remain active.

| Stock | Fixed quantity per grid | Half-grid order quantity | Two-grid quantity |
| --- | ---: | ---: | ---: |
| MU | 0.570 | 0.285 | 1.140 |
| SNDK | 0.372 | 0.186 | 0.744 |
| AMD | 0.898 | 0.449 | 1.796 |
| NVDA | 2.290 | 1.145 | 4.580 |
| INTC | 5.234 | 2.617 | 10.468 |

Quantities correspond approximately to 500 USDC per grid and 250 USDC per half-grid using the 2026-10-15 market snapshot. Fixed quantities do not track a fixed dollar order size as prices change; the original live nominal cap can therefore block a second grid. Exchange minima and common quantity steps are in `market_constraints`.

Fee estimates assume **Lighter Standard (0 taker fee)** and **Arcus Base (0.0225% taker fee)**: four-leg round-trip fees total 0.045%. Verify actual account tiers and adjust both fee tables. The original decision engine deducts its round-trip fee estimate. The first grid closes near 0.4 × the opening threshold; later grids close near the previous grid threshold. Thus the ideal spread capture is 0.6 × 0.15% = 0.09%, or the 0.09% grid step. Subtracting a 0.04% four-leg slippage budget gives a **0.05% net planning assumption**. `profit_per_segment` is retained at 0.09 but is not the unified engine's actual principal close trigger. Actual fills, funding and close guards can change the result.

For a hypothetical 10,000 USDC combined capital, 20% simple APR is 2,000 USDC/year, approximately 5.48 USDC/day (rounded planning target: 5.5). At 0.05% net per complete arbitrage round, this requires approximately 11,000 USDC summed one-leg round notionals daily: **22,000 USDC traded per venue**, or **44,000 USDC across both venues**, counting opens and closes. This is about 22 complete 500-USDC rounds or 44 complete 250-USDC rounds across the strategy, not twice that number per venue. Compare actual daily volume, realized net P&L, fees and funding against these targets. There is no forced-volume order logic or guaranteed APR; opportunity frequency and execution determine results.

## Offline verification and provenance

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```

Tests use synthetic credentials/fake transports. Original tests dependent on private sibling configurations or obsolete currency-specific quantities are excluded from this public suite; stock configuration checks replace those assumptions. No real account execution is certified by offline tests.

The trading source is restored to the original baseline. The only source text exception is a Backpack documentation example replaced with synthetic identifiers; executable logic is unchanged. No source license grant was provided, so this release adds no license terms; existing third-party attribution remains.

Official fee and market references: [Lighter fees](https://docs.lighter.xyz/trading/trading-fees), [Arcus fee tiers](https://api.arcus.xyz/v1/feetiers), [Lighter markets](https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails), [Arcus markets](https://api.arcus.xyz/v1/markets).
