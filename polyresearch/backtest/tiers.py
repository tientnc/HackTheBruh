"""Rate wallets as skilled / unskilled from markets that resolved BEFORE the test period.

Only markets resolved before 1 January 2026 are used, so the 2026 test set is never
seen. For every market a wallet traded, its fills are replayed in time order:

  * BUY adds shares at their cost,
  * SELL realises (sale price - average cost) on the shares sold,
  * shares still held at the end are settled at the payout ($1 if that side won, else $0).

Profit and money spent (total BUY notional) are summed per independent event
(economic_cluster_id), so a ladder of related markets counts once.

Score = (total profit / total money spent) * n / (n + SHRINK), where n is the number of
independent events. The shrink pulls short records towards zero so a few lucky bets
don't top the table (same idea as the team's ranking score, n / (n + 10)).

Tiers:
  * Unrated (left out of tiers.csv): fewer than MIN_EVENTS events or under MIN_SPENT spent,
    or a market maker (buys both YES and NO in most of its markets, many fills),
  * skilled: top SKILLED_SHARE of rated wallets by score AND a positive score,
  * unskilled: every other rated wallet.

Run from the repo root:
  python -m polyresearch.backtest.tiers
  python -m polyresearch.backtest.lobby --tiers analysis/wallet-tiers/v1/tiers.csv
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from .evaluate import read_csv
    from .recommend import load_legs
except ImportError:  # run as a plain script
    from evaluate import read_csv
    from recommend import load_legs

TEST_START = 1767225600  # 2026-01-01T00:00:00Z
DEFAULT_HISTORY = [Path("datasets/finance/resolved-100-2025/v1")]
DEFAULT_OUT = Path("analysis/wallet-tiers/v1")
MIN_EVENTS = 3          # independent events needed to be rated (only 100 pre-2026 markets in the repo)
MIN_SPENT = 100.0       # USDC bought in total, to skip dust wallets
SHRINK = 5              # score shrink: n / (n + SHRINK)
SKILLED_SHARE = 0.10    # top 10% of rated wallets (and positive) are skilled
MM_TWO_SIDED = 0.3      # in a market: smaller side's buys / larger side's buys
MM_MARKET_SHARE = 0.5   # two-sided in at least half its markets ...
MM_MIN_FILLS = 200      # ... with at least this many fills -> market maker


def replay(legs, yes_won):
    """Profit, money spent and two-sidedness for each wallet in one market."""
    pos = defaultdict(lambda: {"yes": [0.0, 0.0], "no": [0.0, 0.0], "pnl": 0.0, "spent": 0.0,
                               "bought": {"yes": 0.0, "no": 0.0}, "fills": 0})
    for leg in legs:  # sorted by time
        w = pos[leg["wallet"]]
        w["fills"] += 1
        shares_cost = w[leg["outcome"]]
        if leg["side"] == "BUY":
            shares_cost[0] += leg["size"]
            shares_cost[1] += leg["notional"]
            w["spent"] += leg["notional"]
            w["bought"][leg["outcome"]] += leg["notional"]
        else:
            held, cost = shares_cost
            if held <= 0:
                continue  # sold shares we never saw bought (e.g. minted); ignore
            sold = min(leg["size"], held)
            avg = cost / held
            w["pnl"] += leg["notional"] * (sold / leg["size"]) - avg * sold
            shares_cost[0] = held - sold
            shares_cost[1] = cost - avg * sold
    out = {}
    for wallet, w in pos.items():
        for side in ("yes", "no"):
            held, cost = w[side]
            payout = 1.0 if (side == "yes") == yes_won else 0.0
            w["pnl"] += held * payout - cost
        big, small = max(w["bought"].values()), min(w["bought"].values())
        out[wallet] = {"pnl": w["pnl"], "spent": w["spent"], "fills": w["fills"],
                       "two_sided": big > 0 and small / big >= MM_TWO_SIDED}
    return out


def score_wallets(history_dirs):
    per_wallet = defaultdict(lambda: {"events": defaultdict(lambda: [0.0, 0.0]), "markets": 0,
                                      "two_sided": 0, "fills": 0})
    used = 0
    for ds in history_dirs:
        ds = Path(ds)
        for m in read_csv(ds / "markets.csv"):
            if int(m["label_available_at"]) >= TEST_START:
                continue  # resolved in the test period: never use
            used += 1
            m.setdefault("folder", f"markets/{m['market_id']}")
            result = replay(load_legs(ds, m), m["yes_outcome"] == "1")
            event = m.get("economic_cluster_id") or m["market_id"]
            for wallet, r in result.items():
                pw = per_wallet[wallet]
                pw["events"][event][0] += r["pnl"]
                pw["events"][event][1] += r["spent"]
                pw["markets"] += 1
                pw["two_sided"] += r["two_sided"]
                pw["fills"] += r["fills"]

    rows = []
    for wallet, pw in per_wallet.items():
        events = {e: v for e, v in pw["events"].items() if v[1] > 0}
        n = len(events)
        spent = sum(v[1] for v in events.values())
        pnl = sum(v[0] for v in events.values())
        ret = pnl / spent if spent else 0.0
        mm = pw["markets"] and pw["two_sided"] / pw["markets"] >= MM_MARKET_SHARE and pw["fills"] >= MM_MIN_FILLS
        rows.append({
            "wallet": wallet,
            "events": n,
            "spent_usdc": round(spent, 2),
            "profit_usdc": round(pnl, 2),
            "return_per_dollar": round(ret, 4),
            "score": round(ret * n / (n + SHRINK), 4),
            "positive_events": sum(1 for v in events.values() if v[0] > 0),
            "market_maker": bool(mm),
        })
    return rows, used


def assign(rows):
    rated = [r for r in rows if r["events"] >= MIN_EVENTS and r["spent_usdc"] >= MIN_SPENT and not r["market_maker"]]
    rated.sort(key=lambda r: (-r["score"], r["wallet"]))
    top = max(1, int(len(rated) * SKILLED_SHARE)) if rated else 0
    for i, r in enumerate(rated):
        r["tier"] = "skilled" if i < top and r["score"] > 0 else "unskilled"
    for r in rows:
        r.setdefault("tier", "")
        r["reason"] = (
            "market maker" if r["market_maker"] else
            f"fewer than {MIN_EVENTS} events" if r["events"] < MIN_EVENTS else
            f"under ${MIN_SPENT:.0f} spent" if r["spent_usdc"] < MIN_SPENT else
            f"rank {rated.index(r) + 1} of {len(rated)}"
        )
    return rated


def run(history_dirs=DEFAULT_HISTORY, out=DEFAULT_OUT):
    rows, used = score_wallets(history_dirs)
    rated = assign(rows)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "tiers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["wallet", "tier", "score", "events"])
        for r in sorted(rated, key=lambda r: r["wallet"]):
            w.writerow([r["wallet"], r["tier"], r["score"], r["events"]])
    fields = ["wallet", "tier", "reason", "score", "return_per_dollar", "events", "positive_events",
              "spent_usdc", "profit_usdc", "market_maker"]
    with (out / "tiers_details.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["tier"] == "", -r["score"], r["wallet"])))
    skilled = [r for r in rated if r["tier"] == "skilled"]
    summary = {
        "history": [Path(d).as_posix() for d in history_dirs],
        "markets_used": used,
        "only_resolved_before": "2026-01-01T00:00:00Z",
        "wallets_seen": len(rows),
        "rated": len(rated),
        "skilled": len(skilled),
        "unskilled": len(rated) - len(skilled),
        "market_makers_excluded": sum(r["market_maker"] for r in rows),
        "skilled_score_floor": min((r["score"] for r in skilled), default=None),
        "rules": {"min_events": MIN_EVENTS, "min_spent_usdc": MIN_SPENT, "shrink": SHRINK,
                  "skilled_share": SKILLED_SHARE},
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"Used {used} markets resolved before 2026; saw {len(rows)} wallets.")
    print(f"Rated {len(rated)}: {len(skilled)} skilled, {len(rated) - len(skilled)} unskilled "
          f"({summary['market_makers_excluded']} market makers left out). Wrote {out / 'tiers.csv'}")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", type=Path, nargs="+", default=DEFAULT_HISTORY,
                    help="dataset folders with markets resolved before 2026 (2025 and earlier)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    run(args.history, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
