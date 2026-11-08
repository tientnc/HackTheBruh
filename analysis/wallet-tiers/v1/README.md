# Wallet ratings v1

**284 wallets rated from 100 Finance markets that resolved before 1 January 2026: 28 skilled, 256 unskilled.** Nothing from the 2026 test markets is used. Every other wallet is Unrated.

[tiers.csv](tiers.csv) (what the app and backtest read) · [tiers_details.csv](tiers_details.csv) (every wallet, with the reason) · [summary.json](summary.json) · [Code](../../../polyresearch/backtest/tiers.py)

## How a wallet is scored

1. Replay every fill in each pre-2026 market in time order. Buying adds shares at their cost. Selling realises the sale price minus the average cost. Shares still held at the end are settled at $1 (side won) or $0.
2. Add up profit and money spent (total bought) per independent event.
3. Score = profit ÷ money spent, shrunk towards zero for short records: × n ÷ (n + 5), where n is the number of events.

## Tiers

| Tier | Rule |
|---|---|
| Unrated | fewer than 3 events, under $100 spent, or a market maker (buys both YES and NO in most of its markets, 200+ fills) |
| Skilled | top 10% of rated wallets by score, with a positive score |
| Unskilled | every other rated wallet |

## Limits

- Only 100 pre-2026 markets are in the repo, so the history bar is low (3 events). Older years can be added with `--history` once collected.
- Profit is rebuilt from trades: fees, rewards, transfers, splits and merges are not included.
- Rated wallets cover part of the 2026 money; most wallets there have no pre-2026 history.

Rebuild:

```powershell
python -m polyresearch.backtest.tiers
python -m polyresearch.backtest.lobby --tiers analysis/wallet-tiers/v1/tiers.csv
```
