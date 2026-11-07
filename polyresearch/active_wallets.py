"""Find active wallets within a resolved-market snapshot, using past evidence only."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .artifacts import manifest
from .dataset import dump, read_table, table
from .research import iso, timestamp
from .wallet_metrics import AS_OF, DATASET

OUTPUT = Path("analysis/active-finance-wallets/before-2025-12-01/v1")


def rank_wallets(dataset, as_of, order="markets"):
    if order not in ("markets", "trade-legs"):
        raise ValueError("Order must be markets or trade-legs")
    wallets = defaultdict(lambda: {"markets": set(), "taker_markets": set(), "trade_leg_rows": 0,
                                   "taker_trade_rows": 0, "notional_usdc": 0.0,
                                   "first_trade_at": None, "last_trade_at": None})
    selected = 0
    for market in read_table(dataset / "markets.csv"):
        label_at = int(market["label_available_at"])
        if label_at >= as_of:
            continue
        selected += 1
        folder = dataset / market["folder"]
        for row in read_table(folder / "wallet_trade_legs.csv.gz"):
            at = int(row["timestamp"])
            if at >= min(as_of, label_at):
                continue
            wallet = wallets[row["wallet"]]
            wallet["markets"].add(market["economic_cluster_id"])
            wallet["trade_leg_rows"] += 1
            wallet["notional_usdc"] += float(row["notional_usdc"])
            wallet["first_trade_at"] = at if wallet["first_trade_at"] is None else min(at, wallet["first_trade_at"])
            wallet["last_trade_at"] = at if wallet["last_trade_at"] is None else max(at, wallet["last_trade_at"])
        # Taker rows overlap the all-side feed; never add them to trade-leg counts.
        for row in read_table(folder / "trades.csv.gz"):
            if int(row["timestamp"]) >= min(as_of, label_at):
                continue
            if row["wallet"] not in wallets:
                raise ValueError("Taker wallet missing from all-side feed")
            wallet = wallets[row["wallet"]]
            wallet["taker_markets"].add(market["economic_cluster_id"])
            wallet["taker_trade_rows"] += 1
    rows = [{"wallet": address, "resolved_markets": len(v["markets"]),
             "resolved_markets_with_taker_trades": len(v["taker_markets"]),
             **{k: v[k] for k in ("trade_leg_rows", "taker_trade_rows", "notional_usdc", "first_trade_at", "last_trade_at")}}
            for address, v in wallets.items()]
    by_legs = sorted(rows, key=lambda r: (-r["trade_leg_rows"], -r["resolved_markets"], r["wallet"]))
    leg_ranks = {r["wallet"]: rank for rank, r in enumerate(by_legs, 1)}
    rows.sort(key=lambda r: (-r["resolved_markets"], -r["trade_leg_rows"], r["wallet"]))
    market_ranks = {r["wallet"]: rank for rank, r in enumerate(rows, 1)}
    if order == "trade-legs":
        rows = by_legs
    for rank, row in enumerate(rows, 1):
        row.update(rank=rank, rank_by_market_count=market_ranks[row["wallet"]],
                   rank_by_trade_leg_count=leg_ranks[row["wallet"]])
    return rows, selected


def build(dataset, out, as_of=AS_OF, top=100, order="markets"):
    if top < 1:
        raise ValueError("Top count must be positive")
    settings = {"dataset": dataset.as_posix(), "as_of": as_of, "top": top, "order": order}
    out.mkdir(parents=True, exist_ok=True)
    if (out / "config.json").exists() and json.loads((out / "config.json").read_text()) != settings:
        raise ValueError("Existing ranking has different settings; use a new output path")
    rows, markets = rank_wallets(dataset, as_of, order)
    selected = rows[:top]
    table(out / "top_wallets.csv", selected, list(selected[0]) if selected else ["wallet", "rank"])
    (out / "wallet_ids.txt").write_text("".join(r["wallet"] + "\n" for r in selected), encoding="utf-8", newline="\n")
    dump(out / "config.json", settings)
    summary = {"as_of": iso(as_of), "source_resolved_markets": markets,
               "observed_wallets": len(rows), "selected_wallets": len(selected),
               "order": order, "minimum_selected_resolved_markets": min((r["resolved_markets"] for r in selected), default=None),
               "selected_with_at_least_5_markets": sum(r["resolved_markets"] >= 5 for r in selected),
               "selected_with_at_least_5_taker_markets": sum(r["resolved_markets_with_taker_trades"] >= 5 for r in selected),
               "scope": "Observed addresses in this selected resolved Finance sample; not a platform-wide top 100",
               "warning": "Activity is not skill. Use a cutoff before forecast/model training to avoid future selection."}
    dump(out / "summary.json", summary)
    manifest(out, [dataset / "manifest.json", dataset / "markets.csv", Path(__file__), Path(__file__).with_name("artifacts.py")])
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--as-of", type=timestamp, default=AS_OF)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--order", choices=("markets", "trade-legs"), default="markets")
    args = parser.parse_args()
    build(args.dataset, args.out, args.as_of, args.top, args.order)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
