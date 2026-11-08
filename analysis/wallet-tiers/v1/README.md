# Finance wallet tiers

Run the API from the repository root, then export its finance wallet list and
classifications:

```sh
.venv/bin/python -m uvicorn backend.main:app --reload
```

In another terminal, run:

```sh
.venv/bin/python analysis/wallet-tiers/v1/export_tiers.py
```

The script calls `GET /wallets/finance` and
`GET /wallets/finance/results`, then writes `tiers.csv` beside the script with
the columns `wallet,tier`. The API must be able to finish its finance
classification before the export request times out. The default timeout is
600 seconds per request; override it with `--timeout` or point to another
server with `--api-url`.

For frontend integration testing, `tiers.frontend-test.csv` is a synthetic
copy with 400 dispersed tier labels changed from `unskilled` to `skilled`.
It preserves the `wallet,tier` schema; the original `tiers.csv` remains
unchanged. Do not use the test copy as classification or research output.
