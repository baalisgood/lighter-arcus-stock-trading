# Lighter–Arcus stock perpetual arbitrage

MU, SNDK, AMD, NVDA, INTC and SPCX use the unified segmented engine with stock basis normalization, value-sized grids and the controls below. Defaults remain **monitor mode**. Offline tests do not certify account permissions, liquidity, profitability or live trading.

## Install and run

Python 3.12 on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-lighter-arcus.txt
bash start.sh check
mkdir -p config/exchanges
cp examples/lighter_config.yaml.example config/exchanges/lighter_config.yaml
cp examples/arcus_config.yaml.example config/exchanges/arcus_config.yaml
chmod 600 config/exchanges/*_config.yaml
# Fill empty authentication fields locally with dedicated stock subaccount credentials.
bash start.sh monitor
# Explicit real trading:
bash start.sh live
```

`check` validates local profiles and decision/execution parity without credentials or network access. The direct `main_unified.py` entry and orchestrator constructor repeat this gate before loading credentials or connecting. Native `monitor` queries accounts but disables order submission. `start_stock_monitor.sh` aliases monitor; `scripts/start_lighter_arcus.sh` defaults to monitor. Set `STOCK_PYTHON` to an absolute interpreter path if needed.

The wrapper clears inherited environment credentials, uses this project's local files, refuses symlinked runtime/authentication paths and holds a process lock. Templates contain no credentials. Do not copy the currency process's credentials. Shutdown uses the engine's emergency-close behavior; stopping a process does not guarantee flat accounts.

## Implemented controls

1. **Natural basis:** fresh Lighter/Arcus BBO mids produce `(midL - midA) / midA × 100`. Each symbol has an in-memory, time-weighted EMA, sampled at most once per second. The 3,600-second EMA warms for a full 3,600 seconds and compares against its value 3,600 seconds ago. Drift above 0.10 percentage points blocks new orders. Missing, invalid or stale BBO and gaps over three seconds reset warmup. Consequently a full hour of continuous fresh paired data is required again after a stream interruption or restart; sparse stock feeds may delay readiness indefinitely. This conservative requirement has not been validated with a one-hour live feed.
2. **Price stability:** both execution prices must stay within 0.05% over two seconds, using the existing stability guard.
3. **Depth:** up to three levels are aggregated inside the BBO-based 0.01% per-leg protection band. Orders are rejected when protected depth cannot cover them. Depth is a snapshot, not a fill guarantee.
4. **First close:** `first_close_ratio: 0.5` sets T0 to half T1. Later grids close at the previous grid threshold. The engine, EMA gates and displays share this ratio; legacy profiles retain their previous 0.4 default.
5. **Funding:** cached, fresh rates retain the adapter/UI eight-hour decimal contract and convert to hourly percent only at the decision boundary. For the configured one-hour holding forecast, only adverse `buy_rate - sell_rate` is deducted. Favorable funding is not prepaid income; missing/nonfinite/stale rates block openings when the funding guard is enabled. `enable_funding_rate_risk` controls this budget and the sustained-adverse guard. Fresh observations adverse by at least `funding_rate_diff_threshold` for `max_unfavorable_funding_hours` trigger the existing risk-close path. Unknown data, favorable rates and observation gaps reset that timer. This is an observed-rate risk estimate, not settled funding P&L or fetched payment history.
6. **Dollar sizing:** each grid targets 500 USDC per leg; each order targets at most 250 USDC per leg at its protected reference price. Quantity uses the larger executable leg price, reserves the execution protection allowance and floors to the common quantity step. A sell may receive price improvement and therefore settle above its reference notional; a sell limit cannot impose an upper fill price. There is no fixed-share fallback. Existing grid occupancy is `sum(remaining_quantity × max(actual_entry_buy, actual_entry_sell))`; price movements do not resize held grids. FIFO entry cost determines how many shares to close to a lower dollar grid. Partial fills record only actual fills. Close chunks avoid leaving an otherwise avoidable remainder below venue minima. An already existing remainder below verified shared minimum quantity/notional remains on the real ledger with an explicit manual-review block on that pair, including new openings. The engine never adds exposure to round up dust or silently deletes it; safe exact reduce-only closure requires confirmed support from both venues. Recovery uses recovered entry prices; missing cost blocks new exposure. Legacy fixed profiles remain supported.
7. **Profile parity:** both YAML files must agree on enabled symbols, fees, order modes, amount mode, grid/order amounts, precision and position caps before account access. Invalid/nonfinite effective per-symbol parameters, missing market constraints and conflicting fixed-quantity overrides are rejected. Protected stock execution supports market mode only; changing both profiles to limit mode is rejected. Legacy profiles retain their modes.
8. **Equity gap:** freshly validated account totals differing by at least 1,000 USDC produce a throttled reminder. This never transfers funds or independently blocks trading.
9. **Cash session:** `America/New_York` regular cash hours, 09:30–16:00, use each symbol's configured T1 (default 0.12%). Other times use 0.18%; step stays 0.07 percentage points. The configured 2026/2027 holidays and early closes apply; unknown years use off-hours thresholds. `closed_overrides` supports emergency closures. A threshold change resets signal persistence. Sessions raise opening thresholds; ordinary closes and risk exits remain available.
10. **Validation:** the public suite uses synthetic data and transports, checks runtime loading and parameter changes, and has no private sibling configuration dependency.

Selling Lighter subtracts basis from raw opening spread; buying Lighter adds it. Closing uses the original position direction, rather than its reversed execution roles or raw spread sign. Raw prices, raw spreads and FIFO costs remain available for execution/accounting. EMA warmup, drift and missing funding only gate openings. When basis is unavailable, ordinary close can use actual FIFO profit as a fallback; the execution layer still applies its FIFO net-profit guard. A moving EMA or a session threshold increase cannot authorize a loss-making ordinary close. Explicit risk exits retain their separate loss-reduction semantics.

## Configuration

Edit `config/arbitrage/arbitrage_segmented.yaml` and keep `arbitrage_lighter_arcus.yaml` execution fields consistent. `monitor_lighter_arcus.yaml` and `multi_exchange_arbitrage.yaml` select the six stocks. No extra or multi-leg symbols are enabled.

| Parameter | Current default |
| --- | ---: |
| Grid amount / maximum order per leg | 500 / 250 USDC |
| Maximum grids / each symbol per-venue cap | 3 / 1,500 USDC |
| Combined per-venue cap, shared by six stocks | 4,500 USDC |
| Dynamic cap | account total × 1.0 |
| Balance warning / block opening / force close | 4,000 / 4,000 / 3,000 USDC |
| Regular T1 / off-hours T1 / step | 0.12% / 0.18% / 0.07 percentage points |
| First close ratio | 0.5 |
| Basis EMA / warmup / drift lookback | 3,600 / 3,600 / 3,600 seconds |
| Maximum basis drift / quote gap | 0.10 percentage points / 3 seconds |
| Funding horizon / maximum cached rate age | 1 hour / 60 seconds |
| Sustained adverse funding threshold / duration | 0.01% hourly / 8 hours |
| Price stability / window | 0.05% / 2 seconds |
| Depth / per-leg protection | 3 levels / 0.01% |
| Price volatility pause | 4% in 300 seconds; pause 900 seconds |
| Equity gap reminder / throttle | 1,000 USDC / 300 seconds |

The combined cap is shared, not allocated equally; six separate 1,500-USDC allowances do not permit 9,000 USDC exposure. Effective exposure is bounded by the static cap, dynamic equity cap and other live guards. Nominal limits do not guarantee margin, capital utilization or maximum loss. Quantity steps and exchange minima remain in `market_constraints`. Adjust per-symbol T1/step/quantity/precision/risk values through symbol overrides; session exceptions and off-hours thresholds can also be overridden per symbol. Maintain the calendar before adding a new year.

## Quantitative expectations

Fee defaults assume **Lighter Standard 0 taker fee** and **Arcus Base 0.0225% taker fee**: round-trip fees are 0.045%. Verify actual tiers and update both tables. Fees are deducted before the opening grid threshold. At regular T1 0.12% and first-close ratio 0.5, ideal gross convergence capture after that opening fee budget is 0.06 percentage points. Subtracting four legs of 0.01% slippage leaves approximately **0.02% before funding**. A later grid's 0.07-point convergence leaves approximately **0.03% before funding**. Actual fills, changing basis, partial execution and funding can differ materially. `profit_per_segment` is not the principal unified-engine close trigger.

For hypothetical combined capital of 10,000 USDC, 20% simple APR means about 5.48 USDC/day. The previous 22,000-USDC daily volume per venue assumes **0.05% net per completed round**. Under 0.02% or 0.03% net assumptions, the corresponding volume is approximately **54,800 or 36,500 USDC per venue per day**, counting opens and closes. These are arithmetic scenarios, not forecasts or promised returns. There is no forced-volume controller or guaranteed 20% APR; evaluate realized net P&L, actual fees, settled funding and executed volume separately.

## Offline checks and sources

```sh
.venv/bin/pip install pytest pytest-asyncio
.venv/bin/python -m pytest tests -q
bash start.sh check
```

Tests use fake transports and synthetic credentials. Live account, long-duration streaming, recovery after a real partial fill and actual profitability require separate operational verification. No new production dependency is required. No source license grant was supplied; this release adds no license terms and retains third-party attribution. The existing Backpack documentation example remains synthetic.

Official references: [Lighter funding](https://docs.lighter.xyz/trading/funding), [Lighter fees](https://docs.lighter.xyz/trading/trading-fees), [Arcus fee tiers](https://api.arcus.xyz/v1/feetiers), [NYSE calendar](https://www.nyse.com/trade/hours-calendars), [Lighter markets](https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails), [Arcus markets](https://api.arcus.xyz/v1/markets).
