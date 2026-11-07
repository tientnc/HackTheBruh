# HackTheBruh

**Do successful wallets move before the crowd?** Starting with [Polymarket Finance](https://polymarket.com/finance).

**First backtest: 100 resolved finance markets → top/bottom wallet deciles → later outcomes.**

**[Explore the 100-market dataset →](datasets/finance/resolved-100-2025/v1/README.md)** · [Single-market Anthropic example](datasets/finance/anthropic-ipo-1_25t-1_5t/v1/README.md)

![100 resolved finance markets: 12,282 observed wallets, 25,473 taker trade records and 10,638 price observations.](datasets/finance/resolved-100-2025/v1/overview.svg)

![Proposed backtest: 51 earlier markets for ranking, 26 for development and 23 for testing. Only earlier available labels may enter wallet rankings.](datasets/finance/resolved-100-2025/v1/backtest.svg)

The resolved sample has final labels from **September–December 2025**. Rankings and forecasts are the next experiment; the dataset includes verified outcomes, not model results.

## Try it

Python 3.11+ · No API key · No third-party runtime dependencies

**1 · Activate the environment**

```powershell
# .venv already exists locally. Create it after a fresh clone.
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python` below.

**2 · Verify the downloaded dataset**

```powershell
python -m polyresearch.resolved_dataset --verify-only
```

**3 · Collect a fresh snapshot**

```powershell
python -m polyresearch.resolved_dataset --out data/resolved-100-fresh
```

The 100-market selection rules are configured. Use a new output directory for each snapshot.

**4 · Check the tests**

```powershell
python -m unittest discover -s tests -v
```

Top/bottom deciles are relative historical rankings. Wallets without enough earlier evidence remain unknown.

[Research: how should we define wallet skill? →](docs/research/wallet-skill.md)

[Experiment: rank wallets first, predict later →](docs/research/resolved-market-backtest.md)

[Methodology, assumptions & API references →](docs/methodology.md)
