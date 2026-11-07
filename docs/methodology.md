# Methodology and data notes

Research question: **Do historically profitable wallets provide a useful signal about future Polymarket odds?**

Start with [Polymarket Finance](https://polymarket.com/finance). This repository contains a working Python data collector and an interpretable wallet baseline. It does **not** yet train a forecasting model or turn wallet agreement into a probability.

## Run

Python 3.11+ and Git are sufficient. The collector uses the standard library, public read-only endpoints, and no API keys. Run commands from this repository; installation is optional.

```powershell
python -m polyresearch --help

# Include closed markets when finding candidates for the original historical window.
# All dates are UTC; end is exclusive. Increase the cap to scan more of the universe.
python -m polyresearch discover --start 2025-08-01 --end 2026-01-01 --max-events 100 --out data/finance-2025.json

# Inspect the saved markets and copy one slug, then collect its history.
python -m polyresearch collect --markets data/finance-2025.json --slug REPLACE_WITH_MARKET_SLUG --start 2025-08-01 --end 2026-01-01 --out data/market-2025

# Freeze wallet classifications BEFORE the flow being analyzed.
# This samples up to 10 taker wallets observed in the collected market.
python -m polyresearch wallets --trades data/market-2025/trades.json --as-of 2025-08-01 --max-wallets 10 --min-trades 100 --min-profit 0 --out data/wallets-2025.json

python -m polyresearch cohorts --trades data/market-2025/trades.json --snapshots data/wallets-2025.json --min-trades 100 --min-profit 0 --out data/cohorts-2025.json

python -m unittest discover -s tests -v
```

Use a new output path for each run. Existing artifacts are never silently replaced. A collection without `manifest.json` did not finish; any files already written remain available for inspection. Local datasets under `data/` are ignored by Git.

For a small live smoke test, use `discover --status open --max-events 5`, select an open child market, and collect a short recent window with `--max-pages 1`. This intentionally samples the feed and can leave older history uncovered.

## Baseline definition

At an exclusive cutoff `t`, a wallet is classified as:

- `skilled`: at least `N` historical trade rows and realized trading profit strictly greater than `P`.
- `unskilled`: sufficient source history is available, but the rule is not met. This is a baseline label, not proof of inability.
- `unknown`: historical P&L is unavailable, a request failed, or trade pagination hit its cap.

Defaults: `N=100`, `P=0` USDC. These are starting assumptions, not empirically validated thresholds. Profit is `realized_market_pnl + realized_combo_pnl`; it excludes AMM liquidity provision, rewards, rebates and unrealized gains. It is not a net-of-all-fees investment return. Both counts and profit are lifetime, all-market metrics before the cutoff, not finance-specific performance. Counts are rows from the wallet feed with makers and takers included, rather than the profile's distinct-market statistic or the P&L series' maker-attributed count. Raw responses are retained because fill-ID and counting limitations matter.

Wallet P&L is requested as a historical series. Only observations **before** `t` are eligible, and the selected observation timestamp and source fidelity are saved. Missing historical values remain missing; current lifetime profit never substitutes for historical profit. A stale observation is exposed rather than interpolated. This is retrospective reconstruction; provider corrections and original publication latency are not known.

## The four groups

Within one binary YES/NO market, compute each observed taker's signed cash flow:

| Action | Contribution |
| --- | --- |
| Buy YES | `+size * price` |
| Sell NO | `+size * price` |
| Sell YES | `-size * price` |
| Buy NO | `-size * price` |

Positive net flow means `agree`; negative means `disagree`. Cross with `skilled`/`unskilled` to obtain the four proposed groups. Unknown and neutral wallets remain separate. Each wallet's net contribution is capped at +/-1,000 USDC by default. A wallet's group is based on its net flow over the whole selected interval; for daily features, run this calculation on daily windows with pre-window snapshots.

This measures directional trading behavior, not holdings or personal beliefs. YES and NO cash flows are an interpretable heuristic, not equivalent measures of underlying exposure at different prices. Maker behavior, hedging, bots, related wallets and self-trading can affect interpretation. Non-YES/NO rows are skipped and counted. Wallet fractions and signed flows are **features**, not calibrated outcome probabilities.

## Data and coverage

- **Discovery:** Gamma's finance tag is resolved by slug rather than hard-coded. Events are scanned in ID order, including closed events by default. Child markets are filtered by approximate date overlap. A bounded scan is explicitly marked incomplete. Current tags, statuses, and `price_now` fields must not be used as historical model features. Missing or changed tags can bias the market universe.
- **Trades:** Data API **v2** uses cursor pagination. Market-shaped requests ignore date filters and serve a fixed three-year window; this collector walks the bounded feed and applies `[start, end)` locally. `pagination_exhausted=false` means the sample is incomplete. The market feed is taker-only to avoid counting both sides as separate signals. Wallet history requests include both roles and use the API's supported user time filters.
- **Prices:** V2 explicit windows are limited to 15 days, so longer intervals are split. The default three-hour buckets suit older history; finer history has shorter retention. Empty history is unavailable data, never a zero price. Each point keeps its actual `resolution_seconds`; its aggregate must not enter features before `timestamp + resolution_seconds`. Settlement points cannot be used as pre-resolution signals.
- **Provenance:** Raw pages, requested windows, fetch timestamps and pagination flags are stored. Identical trade rows are retained: transaction hashes are not unique fill identifiers. Exhausting an API response is not a guarantee of full on-chain coverage.
- **Sampling:** Wallets are selected in lexicographic address order up to `--max-wallets`. Unsampled or unavailable wallets remain unknown. This bounded demo sample is not representative of all traders.

Official references: [market discovery](https://docs.polymarket.com/market-data/discover-markets), [Data API v2 schema](https://data-api.polymarket.com/v2/openapi.json), [v2 migration](https://docs.polymarket.com/migrate/data-api-v1-to-v2).

## Next experiment

1. Audit August-December 2025 coverage for a narrow finance family, including losing and resolved markets. Collect earlier wallet history to score the first training windows.
2. Build daily features from only observations available at each cutoff. Include current price, recent price changes and the four wallet-group flows. Test sensitivity to wallet thresholds and concentration caps.
3. Predict the market price 7 or 30 days later. Fit a small regularized model on earlier dates, validate on later dates, and leave a horizon-sized gap to prevent overlapping targets leaking across splits.
4. Compare price MAE against both `future_price = current_price` and the same model without wallet-skill features. Reserve 2026 data for a frozen out-of-sample evaluation. It must not affect thresholds, feature selection or training.

Forecasting future market prices and forecasting final event outcomes are separate tasks. Brier score or log loss belongs to resolved binary-outcome evaluation, not a regression target consisting of future market prices.
