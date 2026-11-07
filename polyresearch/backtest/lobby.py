"""Build the Jett Showdown Lobby data from the 2026 test markets.

For every usable T-24h test question (test_questions.csv), this freezes the
market 24 hours before it closed and writes what the Lobby shows:

  * the YES price at that moment (same price rule as evaluate.py),
  * the money on YES and NO, split by wallet tier (same holdings rule and
    tiers file as recommend.py, so the Lobby matches the backtest),
  * the recommendation from recommend.py's rule (YES / NO / INSUFFICIENT),
  * the real outcome, so the page can reveal the showdown,
  * a 14-day history of skilled share vs price, and the biggest positions.

Output (read by the frontend):
  frontend/src/data/markets.json   one object per market
  frontend/src/data/meta.json      where the numbers came from

Run from the repo root:
  python -m polyresearch.backtest.lobby                       # no ratings yet: all money "unrated"
  python -m polyresearch.backtest.lobby --tiers tiers.csv     # real ratings (wallet, tier)
  python -m polyresearch.backtest.lobby --fake-tiers          # random tiers, layout preview ONLY

Wallets missing from the tiers file are "unknown". The frontend stores them
under the key "new" and labels them "Unrated".
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from .evaluate import DEFAULT_DATASET, price_at, read_csv, reference_end, yes_prices
    from .recommend import (MIN_POSITION_USD, fake_tier, load_legs, load_tiers,
                            recommend, six_numbers)
except ImportError:  # run as a plain script
    from evaluate import DEFAULT_DATASET, price_at, read_csv, reference_end, yes_prices
    from recommend import (MIN_POSITION_USD, fake_tier, load_legs, load_tiers,
                           recommend, six_numbers)

DEFAULT_OUT = Path("frontend/src/data")
SNAPSHOT = "T-24h"
HISTORY_DAYS = 14
TOP_POSITIONS = 8
CATEGORY = {
    "equities_and_corporate": "Equities",
    "commodities": "Commodities",
    "ipos_and_deals": "IPOs & deals",
    "rates_and_macro": "Rates & macro",
}
FRONTEND_TIER = {"skilled": "skilled", "unskilled": "unskilled", "unknown": "new"}


def iso(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def positions_before(legs, as_of):
    """Like recommend.holdings_before, but keeps shares too (for entry prices).

    Returns {wallet: {"yes": [shares, cost], "no": [shares, cost]}}. The cost
    numbers are identical to holdings_before (tested in lobby_check)."""
    pos = defaultdict(lambda: {"yes": [0.0, 0.0], "no": [0.0, 0.0]})
    for leg in legs:  # sorted by time
        if leg["timestamp"] >= as_of:
            break
        p = pos[leg["wallet"]][leg["outcome"]]
        if leg["side"] == "BUY":
            p[0] += leg["size"]
            p[1] += leg["notional"]
        else:
            held = p[0]
            if held <= 0:
                continue
            sold = min(leg["size"], held)
            p[1] -= p[1] * sold / held
            p[0] = held - sold
    return pos


def holdings_from(pos):
    return {w: {s: v[s][1] for s in ("yes", "no")} for w, v in pos.items()}


def volume_before(dataset, market, as_of):
    rows = read_csv(Path(dataset) / market["folder"] / "trades.csv.gz")
    return round(sum(float(r["notional_usdc"]) for r in rows if int(r["timestamp"]) < as_of), 2)


def side_block(numbers, side):
    return {
        "skilled_usd": numbers[f"skilled_{side}_usd"],
        "unskilled_usd": numbers[f"unskilled_{side}_usd"],
        "new_usd": numbers[f"unknown_{side}_usd"],
        "skilled_wallets": numbers[f"skilled_{side}_wallets"],
        "unskilled_wallets": numbers[f"unskilled_{side}_wallets"],
        "new_wallets": numbers[f"unknown_{side}_wallets"],
    }


def skilled_share(numbers):
    total = numbers["skilled_yes_usd"] + numbers["skilled_no_usd"]
    return None if total <= 0 else round(numbers["skilled_yes_usd"] / total, 4)


def build_market(dataset, market, question, tier_of):
    as_of = int(question["as_of"])
    legs = load_legs(dataset, market)
    pos = positions_before(legs, as_of)
    numbers = six_numbers(holdings_from(pos), tier_of)
    call, _ = recommend(numbers)
    outcome = "yes" if market["yes_outcome"] == "1" else "no"

    points = yes_prices(dataset, market)
    history = []
    for k in range(HISTORY_DAYS - 1, -1, -1):
        t = as_of - k * 86400
        price, _ = price_at(points, t)
        if price is None:
            continue
        n = numbers if k == 0 else six_numbers(holdings_from(positions_before(legs, t)), tier_of)
        history.append({"date": iso(t), "skilled_yes_share": skilled_share(n), "yes_price": price})

    seats = []
    for wallet, sides in pos.items():
        for side in ("yes", "no"):
            shares, cost = sides[side]
            if cost >= MIN_POSITION_USD and shares > 0:
                seats.append({"wallet": wallet, "tier": FRONTEND_TIER[tier_of(wallet)], "side": side,
                              "stake_usd": round(cost, 2), "entry_price": round(cost / shares, 4)})
    seats.sort(key=lambda s: -s["stake_usd"])

    meta = json.loads((Path(dataset) / market["folder"] / "market.json").read_text(encoding="utf-8"))
    return {
        "id": market["market_id"],
        "question": market["question"],
        "category": CATEGORY.get(market["subfield"], market["subfield"].replace("_", " ").title()),
        "closes_at": iso(reference_end(market)),
        "snapshot_at": iso(as_of),
        "resolved_at": iso(market["label_available_at"]),
        "yes_price": float(question["market_yes_price"]),
        "volume_usd": volume_before(dataset, market, as_of),
        "yes": side_block(numbers, "yes"),
        "no": side_block(numbers, "no"),
        "outcome": outcome,
        "call": call,
        "skilled_share": skilled_share(numbers),
        "source_url": meta.get("source_url"),
        "skilled_share_history": history,
        "top_positions": seats[:TOP_POSITIONS],
    }


def run(dataset=DEFAULT_DATASET, out=DEFAULT_OUT, tiers_path=None, fake=False):
    dataset, out = Path(dataset), Path(out)
    if fake:
        tier_of, source = fake_tier, "fake"
        print("Using FAKE random wallet tiers: layout preview only, never present these.")
    elif tiers_path:
        tiers = load_tiers(tiers_path)
        tier_of, source = (lambda w: tiers.get(w, "unknown")), Path(tiers_path).name
        print(f"Loaded {len(tiers)} rated wallets from {tiers_path}")
    else:
        tier_of, source = (lambda w: "unknown"), "none"
        print("No tiers file: every wallet is unrated until you pass --tiers.")

    markets = {m["condition_id"]: m for m in read_csv(dataset / "markets.csv")}
    questions = [q for q in read_csv(dataset / "test_questions.csv")
                 if q["snapshot"] == SNAPSHOT and q["usable"] == "True"]
    rows = []
    for i, q in enumerate(questions, 1):
        rows.append(build_market(dataset, markets[q["condition_id"]], q, tier_of))
        if i % 20 == 0:
            print(f"  {i}/{len(questions)} markets")
    rows.sort(key=lambda r: r["closes_at"], reverse=True)

    out.mkdir(parents=True, exist_ok=True)
    (out / "markets.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    info = {
        "snapshot": SNAPSHOT,
        "tiers_source": source,
        "dataset": dataset.as_posix(),
        "markets": len(rows),
        "skipped_unusable": sum(1 for q in read_csv(dataset / "test_questions.csv")
                                if q["snapshot"] == SNAPSHOT and q["usable"] != "True"),
        "generated_at": iso(datetime.now(tz=timezone.utc).timestamp()),
    }
    (out / "meta.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    calls = defaultdict(int)
    for r in rows:
        calls[r["call"]] += 1
    print(f"Wrote {len(rows)} markets to {out / 'markets.json'} ({dict(calls)})")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--tiers", type=Path, help="CSV with columns wallet, tier")
    ap.add_argument("--fake-tiers", action="store_true", help="random tiers, layout preview only")
    args = ap.parse_args()
    run(args.dataset, args.out, args.tiers, args.fake_tiers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
