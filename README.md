# Lighter–Arcus stock arbitrage

A standalone stock profile for **MU, SNDK, NVDA, AMD and INTC** perpetuals on Lighter and Arcus. The public monitor requires no credentials. Live mode uses the full unified segmented decision, execution, risk and recovery engine, with two market-order legs and first-level depth checks. No cryptocurrency fallback is permitted.

## Install and run

Use Python 3.12 on macOS or Linux. From a clean clone:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-lighter-arcus.txt
export STOCK_PYTHON="$PWD/.venv/bin/python"
./start.sh check
./start.sh monitor
```

`check` validates local profile configuration without connecting accounts or sending orders. `monitor` only subscribes to public quotes. `start_stock_monitor.sh` remains a public-monitor alias.

To enable **real orders**, create dedicated stock subaccounts on both venues and configure their credentials locally:

```sh
cp .env.stock.example .env.stock
chmod 600 .env.stock
# Edit .env.stock locally; all example values are intentionally blank.
./start.sh live
```

Lighter requires its API private key, account index and API key index. Arcus requires the wallet address, dedicated Ed25519 API public/signing keys and account index. Every field is required, including explicit indices. `.env.stock` is ignored by Git. Shared `.env`, exchange authentication YAML, parent project files and inherited credentials/proxies/PYTHONPATH are not used by this launcher. Official HTTPS/WSS endpoints and TLS verification are enforced. Do not put credentials into configuration files or issue reports.

Live mode sends real market orders. The release has offline tests using fake adapters; no real account execution or live fill was verified for this release. Stopping a process does **not** guarantee positions are closed. Reconcile both accounts and open orders after failures or shutdown.

## Default execution limits

| Limit | Enforcement |
| --- | --- |
| Per opening order, per leg | At most 500 USDC nominal |
| Per stock, per venue | At most 2,000 USDC nominal including existing exposure |
| All stocks, per venue | At most 8,000 USDC nominal including existing exposure |
| Conservative collateral budget, per venue | At most 1,500 USDC at **1× nominal** |

The collateral calculation deliberately reserves full nominal value, assumes no leverage or offsets, and does not change exchange leverage. It is **not** the venue's actual initial-margin formula. Consequently the default effective total nominal limit is **1,500 USDC per venue**, reached before the 8,000 ceiling. The independent ceilings are still checked immediately before submission. Limits stop new opens; they do not cap losses or guarantee market fills.

The order size uses the larger fresh price across both venues, a 0.01% per-leg protection allowance (plus conservative tick rounding), available first-level depth and a quantity step common to both venues, rounded down. Actual market metadata supplies minimum quantity/notional and Lighter price/size scaling. Missing, duplicate, inactive or invalid metadata, quotes, depth, balances, positions or order state blocks new orders. A shared open lock covers execution and recording, so queued symbols see confirmed exposure before rechecking the budget. Unknown fills block subsequent opening attempts pending reconciliation.

The estimate includes four taker fees: Lighter 0.028% and Arcus 0.0225% on entry and exit, totaling 0.101%. An additional 0.04% round-trip slippage allowance is deducted once: 0.01% per leg across both entry and exit. The initial net advantage threshold is 0.10%, giving an estimated initial raw spread requirement of approximately 0.241%; the public monitor screens at 0.30%. These are conservative configuration estimates, not a promise of profit or the account's actual fee tier.

## Recovery and close behavior

Startup queries both accounts and outstanding orders before enabling new opens. Matched positions are recovered using aggregate quantity and venue entry averages, as one synthetic grid whose fixed base is the entire recovered quantity. **Historical FIFO lots and per-fill fees cannot be reconstructed** from this aggregate recovery; online trades retain the engine's FIFO segment accounting. Within each position cycle, the first confirmed common fill fixes the grid base for subsequent opening targets, closing targets and persistence thresholds. Live depth and price can reduce an individual order size without moving that base; confirmed flat clears it. Recovery with missing/unmatched legs, unrecognized exposure, stale account snapshots or uncertain orders keeps new opens locked. Do not reuse the profile against accounts containing unrelated positions.

Normal closes recheck confirmed positions, fresh quotes and FIFO costs, and submit reduce-only orders. Reduce-only closes are exempt from the opening-order 500 USDC ceiling and minimum opening notional, so an appreciated position, aggregate recovery or small remaining notional can be reduced; common quantity precision, venue minimum quantity and confirmed position checks remain enforced. One-leg failure follows the existing reconciliation/unknown-order protections; it never establishes that the other leg did not fill. Inspect both accounts before manually intervening.

## Offline verification

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```

Tests cover public monitoring, real unified/executor flows with fake exchange adapters, limits, precision, stale/missing state, concurrent requests, reduce-only closes and transport rejection. They do not contact trading accounts.

## License and attribution

The source snapshot supplied for this release did not include a license file or an explicit license grant. This release adds no license terms. Existing third-party attribution and copyright markers remain in the included source; dependencies retain their respective licenses.
