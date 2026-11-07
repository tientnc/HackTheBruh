"""Mark a prediction system against a resolved-market dataset.

Works on the folder written by resolved_dataset.py (markets.csv plus
markets/<id>/prices.csv.gz). Three commands:

  questions  Write test_questions.csv: for each market and snapshot, the
             as-of time and the market's YES price at that moment (the
             crowd forecast to beat). Hand this file to the prediction team.

  fake       Write fake predictions (market price plus noise) to check the
             marking works. Fake predictions should NOT beat the market.

  score      Mark a predictions CSV. Two formats are accepted:
               right/wrong (MVP):  condition_id, snapshot, recommendation
                                   where recommendation is YES, NO or INSUFFICIENT
               probability:        condition_id, snapshot, p_yes

Examples
  python -m polyresearch.backtest.evaluate questions --dataset datasets/finance/resolved-2026/v1
  python -m polyresearch.backtest.evaluate fake      --dataset datasets/finance/resolved-2026/v1
  python -m polyresearch.backtest.evaluate score     --dataset datasets/finance/resolved-2026/v1 \
      --predictions datasets/finance/resolved-2026/v1/recommendations_fake.csv

No-look-ahead rule for the prediction team: a prediction for snapshot S of a
market may only use data available before that row's as_of time, and wallet
skill may only be scored from markets resolved before the test window starts.
"""

import argparse
import csv
import gzip
import io
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATASET = Path("datasets/finance/resolved-2026/v1")  # TEST data, not the 2025 training set
SNAPSHOTS = {"T-24h": 24 * 3600, "T-7d": 7 * 24 * 3600}
MAX_PRICE_LAG_HOURS = 36       # a snapshot price older than this is marked unusable
GAP_BUCKETS = [(0, 5), (5, 15), (15, 101)]
TRADE_THRESHOLDS = [5, 10, 15, 20]
BOOTSTRAP_ROUNDS = 2000
SEED = 7


# ---------------------------------------------------------------- small helpers
def read_csv(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path = Path(path)
    fields = fields or (list(rows[0]) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def to_ts(value):
    """Epoch seconds from an int-like string or an ISO date/time."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    s = s.replace(" ", "T", 1).replace("Z", "+00:00")
    if len(s) >= 3 and s[-3] in "+-" and s[-6] not in "+-":
        s += ":00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def brier(p, y):
    return (p - y) ** 2


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


# ---------------------------------------------------------------- questions
def reference_end(market):
    """When the question was effectively settled: the earlier of the scheduled
    end date and the time the label became available. Using the earlier one
    avoids snapshots that fall after the real-world event already happened."""
    label = int(market["label_available_at"])
    scheduled = to_ts(market.get("scheduled_end_date"))
    return min(label, scheduled) if scheduled else label


def yes_prices(dataset, market):
    rows = read_csv(Path(dataset) / market["folder"] / "prices.csv.gz")
    rows = [r for r in rows if r["outcome"].strip().lower() == "yes"]
    return sorted(((int(r["available_at"]), float(r["price"])) for r in rows))


def price_at(points, as_of):
    """Latest YES price whose bucket had finished by as_of. Returns (price, available_at)."""
    best = None
    for available_at, price in points:
        if available_at <= as_of:
            best = (price, available_at)
        else:
            break
    return best if best else (None, None)


def build_questions(dataset):
    dataset = Path(dataset)
    markets = read_csv(dataset / "markets.csv")
    rows = []
    for m in markets:
        points = yes_prices(dataset, m)
        end = reference_end(m)
        opened = to_ts(m.get("trading_start"))
        for name, offset in SNAPSHOTS.items():
            as_of = end - offset
            price, seen = price_at(points, as_of)
            lag = None if seen is None else round((as_of - seen) / 3600, 1)
            usable = (price is not None and lag <= MAX_PRICE_LAG_HOURS
                      and (opened is None or as_of > opened))
            rows.append({
                "condition_id": m["condition_id"], "market_id": m["market_id"],
                "snapshot": name, "as_of": as_of, "as_of_utc": iso(as_of),
                "question": m["question"], "market_yes_price": price,
                "price_lag_hours": lag, "usable": usable,
            })
    out = dataset / "test_questions.csv"
    write_csv(out, rows)
    usable = [r for r in rows if r["usable"]]
    print(f"Wrote {out}")
    for name in SNAPSHOTS:
        n = sum(1 for r in usable if r["snapshot"] == name)
        print(f"  {name}: {n} usable of {len(markets)} markets")
    return rows


# ---------------------------------------------------------------- fake predictions
def build_fake(dataset, noise=0.10):
    dataset = Path(dataset)
    questions = load_questions(dataset)
    rng = random.Random(SEED)
    rows = []
    for q in questions.values():
        if not q["usable"]:
            continue
        p = min(0.99, max(0.01, float(q["market_yes_price"]) + rng.gauss(0, noise)))
        rows.append({"condition_id": q["condition_id"], "snapshot": q["snapshot"], "p_yes": round(p, 4)})
    out = dataset / "predictions_fake.csv"
    write_csv(out, rows, ["condition_id", "snapshot", "p_yes"])
    print(f"Wrote {out} ({len(rows)} rows). Scoring it should show the market winning.")

    # Same noisy guesses turned into YES / NO / INSUFFICIENT recommendations.
    recs = []
    for r in rows:
        p = r["p_yes"]
        rec = "INSUFFICIENT" if rng.random() < 0.2 else ("YES" if p > 0.5 else "NO")
        recs.append({"condition_id": r["condition_id"], "snapshot": r["snapshot"], "recommendation": rec})
    out = dataset / "recommendations_fake.csv"
    write_csv(out, recs, ["condition_id", "snapshot", "recommendation"])
    print(f"Wrote {out} ({len(recs)} rows). It should be right about as often as the crowd, not more.")


# ---------------------------------------------------------------- scoring
def load_questions(dataset):
    path = Path(dataset) / "test_questions.csv"
    if not path.exists():
        build_questions(dataset)
    out = {}
    for r in read_csv(path):
        r["usable"] = r["usable"] == "True"
        out[(r["condition_id"], r["snapshot"])] = r
    return out


def cluster_bootstrap(rows, rounds=BOOTSTRAP_ROUNDS):
    """95% interval for (model Brier - market Brier), resampling whole clusters
    so related markets are not counted as independent evidence."""
    by_cluster = defaultdict(list)
    for r in rows:
        by_cluster[r["cluster"]].append(r["model_brier"] - r["market_brier"])
    clusters = list(by_cluster.values())
    if len(clusters) < 5:
        return None
    rng = random.Random(SEED)
    diffs = []
    for _ in range(rounds):
        sample = [d for _ in clusters for d in rng.choice(clusters)]
        diffs.append(mean(sample))
    diffs.sort()
    return diffs[int(0.025 * rounds)], diffs[int(0.975 * rounds) - 1]


def wilson(hits, n, z=1.96):
    """95% range for a hit rate, so 7/10 isn't read as certain."""
    if n == 0:
        return None
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def score_recommendations(dataset, predictions_path, markets, questions, preds):
    """Right/wrong marking for YES / NO / INSUFFICIENT recommendations."""
    problems, rows = [], []
    for p in preds:
        key = (p["condition_id"], p["snapshot"])
        q = questions.get(key)
        if q is None:
            problems.append(f"unknown market/snapshot {key}")
            continue
        if not q["usable"]:
            continue
        rec = (p.get("recommendation") or "").strip().upper()
        if rec not in ("YES", "NO", "INSUFFICIENT"):
            problems.append(f"recommendation must be YES, NO or INSUFFICIENT for {key} (got {rec!r})")
            continue
        m = markets[p["condition_id"]]
        actual = "YES" if int(m["yes_outcome"]) == 1 else "NO"
        price = float(q["market_yes_price"])
        crowd = "YES" if price > 0.5 else "NO" if price < 0.5 else "TIE"
        rows.append({
            "condition_id": p["condition_id"], "snapshot": p["snapshot"],
            "question": m["question"], "recommendation": rec, "actual": actual,
            "market_yes_price": price, "crowd_pick": crowd,
            "model_right": "" if rec == "INSUFFICIENT" else rec == actual,
            "crowd_right": "" if crowd == "TIE" else crowd == actual,
        })

    report = {"dataset": str(dataset), "predictions": str(predictions_path), "mode": "right_or_wrong",
              "scored_at": iso(int(datetime.now(timezone.utc).timestamp())),
              "problems": problems[:50], "snapshots": {}}
    print(f"\nMarking {predictions_path}  (right/wrong)")
    print(f"Dataset: {dataset}  ({len(markets)} markets)")
    if problems:
        print(f"  {len(problems)} rows ignored, e.g. {problems[0]}")

    for name in SNAPSHOTS:
        rs = [r for r in rows if r["snapshot"] == name]
        if not rs:
            continue
        made = [r for r in rs if r["recommendation"] != "INSUFFICIENT"]
        model_hits = sum(1 for r in made if r["model_right"])
        crowd_same = [r for r in made if r["crowd_pick"] != "TIE"]
        crowd_hits = sum(1 for r in crowd_same if r["crowd_right"])
        disagree = [r for r in made if r["crowd_pick"] not in ("TIE", r["recommendation"])]
        dis_hits = sum(1 for r in disagree if r["model_right"])

        s = {
            "markets": len(rs),
            "recommendations_made": len(made),
            "insufficient_data": len(rs) - len(made),
            "model_right": model_hits,
            "model_accuracy": model_hits / len(made) if made else None,
            "model_accuracy_95_range": wilson(model_hits, len(made)),
            "crowd_accuracy_same_markets": crowd_hits / len(crowd_same) if crowd_same else None,
            "disagreed_with_crowd": len(disagree),
            "model_right_when_disagreeing": dis_hits / len(disagree) if disagree else None,
            "model_right_when_disagreeing_95_range": wilson(dis_hits, len(disagree)),
        }
        report["snapshots"][name] = s

        print(f"\n== {name} ==  {len(rs)} markets")
        print(f"  Recommendations made:    {len(made)}   (insufficient data: {s['insufficient_data']})")
        if made:
            lo, hi = s["model_accuracy_95_range"]
            print(f"  Model right:             {model_hits}/{len(made)} = {pct(s['model_accuracy'])}"
                  f"   (likely range {lo:.0%} to {hi:.0%})")
            print(f"  Crowd right, same markets: {pct(s['crowd_accuracy_same_markets'])}"
                  f"   (crowd = side priced above 50c)")
        if disagree:
            lo, hi = s["model_right_when_disagreeing_95_range"]
            print(f"  Model disagreed with the crowd on {len(disagree)} markets and was right on {dis_hits}"
                  f" = {pct(s['model_right_when_disagreeing'])}   (likely range {lo:.0%} to {hi:.0%})")
            verdict = ("model genuinely beat the crowd on these" if lo > 0.5 else
                       "crowd genuinely beat the model on these" if hi < 0.5 else
                       "too few to tell yet (range includes 50%)")
            print(f"  -> {verdict}")
        else:
            print("  Model never disagreed with the crowd, so it adds nothing beyond the price yet.")

    stem = Path(predictions_path).stem
    write_csv(dataset / f"scored_{stem}.csv", rows)
    (dataset / f"report_{stem}.json").write_text(json.dumps(report, indent=2))
    print(f"\nSaved scored_{stem}.csv and report_{stem}.json in {dataset}")
    return report


def score(dataset, predictions_path):
    dataset = Path(dataset)
    markets = {m["condition_id"]: m for m in read_csv(dataset / "markets.csv")}
    questions = load_questions(dataset)
    preds = read_csv(predictions_path)
    if preds and "recommendation" in preds[0]:
        return score_recommendations(dataset, predictions_path, markets, questions, preds)

    problems, rows = [], []
    for p in preds:
        key = (p["condition_id"], p["snapshot"])
        q = questions.get(key)
        if q is None:
            problems.append(f"unknown market/snapshot {key}")
            continue
        if not q["usable"]:
            continue
        try:
            prob = float(p["p_yes"])
        except (TypeError, ValueError):
            problems.append(f"bad p_yes for {key}")
            continue
        if not 0 <= prob <= 1:
            problems.append(f"p_yes outside 0-1 for {key}")
            continue
        m = markets[p["condition_id"]]
        y = int(m["yes_outcome"])
        price = float(q["market_yes_price"])
        rows.append({
            "condition_id": p["condition_id"], "snapshot": p["snapshot"],
            "cluster": m.get("economic_cluster_id") or m.get("event_id"),
            "outcome": y, "p_model": prob, "p_market": price,
            "gap_pts": round((prob - price) * 100, 2),
            "model_brier": brier(prob, y), "market_brier": brier(price, y),
        })

    report = {"dataset": str(dataset), "predictions": str(predictions_path),
              "scored_at": iso(int(datetime.now(timezone.utc).timestamp())),
              "problems": problems[:50], "snapshots": {}}

    print(f"\nMarking {predictions_path}")
    print(f"Dataset: {dataset}  ({len(markets)} markets)")
    if problems:
        print(f"  {len(problems)} prediction rows ignored, e.g. {problems[0]}")

    for name in SNAPSHOTS:
        rs = [r for r in rows if r["snapshot"] == name]
        possible = sum(1 for q in questions.values() if q["snapshot"] == name and q["usable"])
        if not rs:
            continue
        model_b, market_b = mean([r["model_brier"] for r in rs]), mean([r["market_brier"] for r in rs])
        ci = cluster_bootstrap(rs)
        direction = mean([1.0 if (r["p_model"] > 0.5) == (r["outcome"] == 1) else 0.0 for r in rs])
        market_dir = mean([1.0 if (r["p_market"] > 0.5) == (r["outcome"] == 1) else 0.0 for r in rs])

        buckets = []
        for lo, hi in GAP_BUCKETS:
            b = [r for r in rs if lo <= abs(r["gap_pts"]) < hi]
            if not b:
                continue
            # When the model disagrees with the price, how often was the model's side right?
            sided = [r for r in b if r["p_model"] != r["p_market"]]
            hit = mean([1.0 if (r["p_model"] > r["p_market"]) == (r["outcome"] == 1) else 0.0 for r in sided])
            buckets.append({"gap": f"{lo}-{hi if hi < 101 else '+'}", "markets": len(b),
                            "model_brier": mean([r["model_brier"] for r in b]),
                            "market_brier": mean([r["market_brier"] for r in b]),
                            "model_side_right": hit})

        trading = []
        for t in TRADE_THRESHOLDS:
            bets = []
            for r in rs:
                if abs(r["gap_pts"]) < t:
                    continue
                if r["p_model"] > r["p_market"]:      # buy YES at the market price
                    cost, won = r["p_market"], r["outcome"] == 1
                else:                                 # buy NO at 1 - price
                    cost, won = 1 - r["p_market"], r["outcome"] == 0
                if cost <= 0:
                    continue
                bets.append((1 / cost - 1) if won else -1.0)
            trading.append({"min_gap_pts": t, "bets": len(bets),
                            "avg_return_per_$1": mean(bets) if bets else None,
                            "win_rate": mean([1.0 if b > 0 else 0.0 for b in bets]) if bets else None})

        verdict = ("model BEATS the market" if ci and ci[1] < 0 else
                   "market BEATS the model" if ci and ci[0] > 0 else
                   "no clear difference (interval includes 0)" if ci else
                   "too few clusters for an interval")
        report["snapshots"][name] = {
            "markets_scored": len(rs), "markets_possible": possible,
            "model_brier": model_b, "market_brier": market_b,
            "brier_diff_95ci": ci, "verdict": verdict,
            "model_direction_right": direction, "market_direction_right": market_dir,
            "by_gap": buckets, "simulated_trading": trading,
        }

        print(f"\n== {name} ==  scored {len(rs)} of {possible} markets")
        print(f"  Brier score (lower is better): model {model_b:.4f}   market {market_b:.4f}")
        if ci:
            print(f"  Model minus market, 95% interval: {ci[0]:+.4f} to {ci[1]:+.4f}")
        print(f"  Verdict: {verdict}")
        print(f"  Called the right side: model {direction:.0%}   market {market_dir:.0%}")
        print("  By size of disagreement (gap in points):")
        for b in buckets:
            print(f"    {b['gap']:>6}: {b['markets']:>3} markets  model {b['model_brier']:.4f}  "
                  f"market {b['market_brier']:.4f}  model's side right {b['model_side_right']:.0%}")
        print("  Simulated betting (buy the side the model prefers when gap >= threshold):")
        for tr in trading:
            if tr["bets"]:
                print(f"    gap >= {tr['min_gap_pts']:>2}: {tr['bets']:>3} bets  "
                      f"avg return {tr['avg_return_per_$1']:+.1%} per $1  win rate {tr['win_rate']:.0%}")
            else:
                print(f"    gap >= {tr['min_gap_pts']:>2}: no bets")

    stem = Path(predictions_path).stem
    write_csv(dataset / f"scored_{stem}.csv", rows)
    (dataset / f"report_{stem}.json").write_text(json.dumps(report, indent=2))
    print(f"\nSaved scored_{stem}.csv and report_{stem}.json in {dataset}")
    return report


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["questions", "fake", "score"])
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--predictions", type=Path, help="CSV with condition_id, snapshot, p_yes (for score)")
    args = ap.parse_args()
    if args.command == "questions":
        build_questions(args.dataset)
    elif args.command == "fake":
        build_fake(args.dataset)
    else:
        if not args.predictions:
            ap.error("score needs --predictions")
        score(args.dataset, args.predictions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())