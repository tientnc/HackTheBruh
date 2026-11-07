"""Turn wallet labels + trade history into YES / NO / INSUFFICIENT recommendations.

For every test question (market + snapshot time in test_questions.csv):
  1. keep only trades made BEFORE the snapshot time (no peeking),
  2. rebuild each wallet's YES and NO holdings from its buys and sells,
  3. label each wallet skilled / unskilled / unknown using the tiers file,
  4. add up the six numbers (money on YES and NO for each label),
  5. apply the rule to get a recommendation.

Output: recommendations.csv in the dataset folder, ready for
  python -m polyresearch.backtest.evaluate score --predictions <that file>

Inputs
  --dataset  folder written by resolved_dataset.py (needs test_questions.csv:
             run `python -m polyresearch.backtest.evaluate questions` first)
  --tiers    CSV with columns: wallet, tier   (tier = skilled or unskilled).
             Wallets missing from the file count as unknown.
             IMPORTANT: tiers must be scored only from markets that resolved
             before the test markets, or the test is meaningless.
  --fake-tiers  ignore --tiers and label wallets at random, to test the pipeline.

Money on a side = what the wallet paid for the shares it still holds
(average-cost: selling part of a position removes that share of its cost).

Known limitation: positions created or closed outside trades (split, merge,
redeem, transfers) are not in the trade feed, so a few holdings may be off.
"""

import argparse
import hashlib
from collections import defaultdict
from pathlib import Path

try:
    from .evaluate import DEFAULT_DATASET, read_csv, write_csv
except ImportError:  # run as a plain script
    from evaluate import DEFAULT_DATASET, read_csv, write_csv

# ---------------------------------------------------------------- the rule
MIN_SKILLED_USD = 1000      # less skilled money than this -> INSUFFICIENT
MIN_SKILLED_WALLETS = 3     # fewer skilled wallets than this -> INSUFFICIENT
MIN_LEAN = 0.10             # skilled share must be at least 60/40 one way, else INSUFFICIENT
MIN_POSITION_USD = 1.0      # ignore dust positions

TIERS = ("skilled", "unskilled", "unknown")


def recommend(numbers):
    """The decision rule. Change it here; everything else stays the same."""
    skilled_total = numbers["skilled_yes_usd"] + numbers["skilled_no_usd"]
    skilled_wallets = numbers["skilled_yes_wallets"] + numbers["skilled_no_wallets"]
    if skilled_total < MIN_SKILLED_USD or skilled_wallets < MIN_SKILLED_WALLETS:
        return "INSUFFICIENT", None
    share_yes = numbers["skilled_yes_usd"] / skilled_total
    if abs(share_yes - 0.5) < MIN_LEAN:
        return "INSUFFICIENT", share_yes
    return ("YES" if share_yes > 0.5 else "NO"), share_yes


# ---------------------------------------------------------------- holdings
def load_tiers(path):
    tiers = {}
    for row in read_csv(path):
        tier = row["tier"].strip().lower()
        if tier in ("skilled", "unskilled"):
            tiers[row["wallet"].strip().lower()] = tier
    return tiers


def fake_tier(wallet):
    """Stable random label for testing: ~10% skilled, ~60% unskilled, rest unknown."""
    x = int(hashlib.sha256(wallet.encode()).hexdigest(), 16) % 100
    return "skilled" if x < 10 else "unskilled" if x < 70 else "unknown"


def holdings_before(legs, as_of):
    """{wallet: {"yes": cost_usd, "no": cost_usd}} from trades strictly before as_of."""
    shares = defaultdict(lambda: {"yes": 0.0, "no": 0.0})
    cost = defaultdict(lambda: {"yes": 0.0, "no": 0.0})
    for leg in legs:  # legs are sorted by time
        if leg["timestamp"] >= as_of:
            break
        w, side = leg["wallet"], leg["outcome"]
        if leg["side"] == "BUY":
            shares[w][side] += leg["size"]
            cost[w][side] += leg["notional"]
        else:
            held = shares[w][side]
            if held <= 0:
                continue  # selling shares we never saw bought (e.g. from a split)
            sold = min(leg["size"], held)
            cost[w][side] -= cost[w][side] * sold / held
            shares[w][side] = held - sold
    return cost


def load_legs(dataset, market):
    rows = read_csv(Path(dataset) / market["folder"] / "wallet_trade_legs.csv.gz")
    legs = []
    for r in rows:
        outcome = r["outcome"].strip().lower()
        if outcome not in ("yes", "no"):
            continue
        legs.append({"timestamp": int(r["timestamp"]), "wallet": r["wallet"].lower(),
                     "side": r["side"].upper(), "outcome": outcome,
                     "size": float(r["size_shares"]), "notional": float(r["notional_usdc"])})
    legs.sort(key=lambda r: r["timestamp"])
    return legs


def six_numbers(holdings, tier_of):
    n = {f"{t}_{s}_{k}": 0 for t in TIERS for s in ("yes", "no") for k in ("usd", "wallets")}
    for wallet, sides in holdings.items():
        tier = tier_of(wallet)
        for side in ("yes", "no"):
            usd = sides[side]
            if usd >= MIN_POSITION_USD:
                n[f"{tier}_{side}_usd"] += usd
                n[f"{tier}_{side}_wallets"] += 1
    for k in n:
        if k.endswith("_usd"):
            n[k] = round(n[k], 2)
    return n


# ---------------------------------------------------------------- main
def run(dataset, tiers_path=None, fake=False, out_name="recommendations.csv"):
    dataset = Path(dataset)
    questions_path = dataset / "test_questions.csv"
    if not questions_path.exists():
        raise SystemExit("No test_questions.csv yet. Run: python -m polyresearch.backtest.evaluate questions")
    if fake:
        tier_of = fake_tier
        print("Using FAKE random wallet labels (for testing only).")
    else:
        if not tiers_path:
            raise SystemExit("Give --tiers <file>, or --fake-tiers to test with random labels.")
        tiers = load_tiers(tiers_path)
        tier_of = lambda w: tiers.get(w, "unknown")
        print(f"Loaded {len(tiers)} labelled wallets from {tiers_path}")

    markets = {m["condition_id"]: m for m in read_csv(dataset / "markets.csv")}
    questions = [q for q in read_csv(questions_path) if q["usable"] == "True"]
    by_market = defaultdict(list)
    for q in questions:
        by_market[q["condition_id"]].append(q)

    rows = []
    for i, (cid, qs) in enumerate(by_market.items(), 1):
        legs = load_legs(dataset, markets[cid])
        for q in qs:
            numbers = six_numbers(holdings_before(legs, int(q["as_of"])), tier_of)
            rec, share = recommend(numbers)
            rows.append({"condition_id": cid, "snapshot": q["snapshot"], "recommendation": rec,
                         "skilled_share_yes": None if share is None else round(share, 4),
                         "market_yes_price": q["market_yes_price"], **numbers})
        if i % 20 == 0:
            print(f"  {i}/{len(by_market)} markets done")

    out = dataset / out_name
    write_csv(out, rows)
    counts = defaultdict(int)
    for r in rows:
        counts[(r["snapshot"], r["recommendation"])] += 1
    print(f"Wrote {out}")
    for snap in sorted({r["snapshot"] for r in rows}):
        print(f"  {snap}: " + ", ".join(f"{rec} {counts[(snap, rec)]}" for rec in ("YES", "NO", "INSUFFICIENT")))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--tiers", type=Path, help="CSV with columns wallet, tier")
    ap.add_argument("--fake-tiers", action="store_true", help="random labels, to test the pipeline")
    ap.add_argument("--out", default=None, help="output file name (default recommendations.csv)")
    args = ap.parse_args()
    name = args.out or ("recommendations_fake_tiers.csv" if args.fake_tiers else "recommendations.csv")
    run(args.dataset, args.tiers, args.fake_tiers, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())