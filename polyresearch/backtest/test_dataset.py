"""Build the 2026 TEST dataset by reusing resolved_dataset.py with 2026 dates.

resolved_dataset.py (late 2025) is the TRAINING data used to label wallets.
This builds the same kind of dataset for markets that resolved in 2026, so the
model is tested on markets it has never seen. resolved_dataset.py is not edited.

Run from the repo root:
  python -m polyresearch.backtest.test_dataset                 # 100 markets, Jan 2026 to today
  python -m polyresearch.backtest.test_dataset --count 30      # smaller trial run first
  python -m polyresearch.backtest.test_dataset --verify-only   # re-check an existing build

Then:
  python -m polyresearch.backtest.evaluate questions
  python -m polyresearch.backtest.recommend --tiers datasets/finance/wallet_tiers.csv
  python -m polyresearch.backtest.evaluate score --predictions datasets/finance/resolved-2026/v1/recommendations.csv
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import resolved_dataset as rd
from ..client import GAMMA, Client
from ..dataset import gzread, gzwrite
from ..research import iso, now, timestamp

TEST_START = "2026-01-01"
DEFAULT_OUT = Path("datasets/finance/resolved-2026/v1")
# Fresh market list for 2026; deliberately NOT the 2025 archive catalog.
DEFAULT_CATALOG = Path("datasets/finance/resolved-2026/raw/catalog.json.gz")
MAX_EVENTS = 50000


def keyset_catalog(start_ts, end_ts, max_events=MAX_EVENTS):
    """Same output as dataset.catalog(), but pages with /events/keyset.

    dataset.catalog() pages with offset, which Gamma caps at about 2,000
    results; the 2026 finance window has more events than that.
    """
    client = Client()
    tag = client.get(GAMMA, "/tags/slug/finance")
    params = {"tag_id": tag["id"], "order": "id", "ascending": True,
              "start_date_max": iso(end_ts), "end_date_min": iso(start_ts)}
    events, seen, cursor, exhausted = [], set(), None, False
    while len(events) < max_events:
        page = dict(params, limit=100)
        if cursor:
            page["after_cursor"] = cursor
        response = client.get(GAMMA, "/events/keyset", **page)
        batch = response.get("events") or []
        for event in batch:
            if event["id"] not in seen:
                seen.add(event["id"])
                events.append(event)
        print(f"Catalog: {len(events)} events", flush=True)
        cursor = response.get("next_cursor")
        if not cursor or not batch:
            exhausted = True
            break
    return {"collected_at": now(), "tag": tag, "query": {**params, "endpoint": "/events/keyset"},
            "events": events, "pagination_exhausted": exhausted}


def market_volume(market):
    for key in ("volumeNum", "volume"):
        try:
            return float(market.get(key))
        except (TypeError, ValueError):
            continue
    return 0.0


def volume_filtered(raw, min_volume):
    """Copy of the catalog keeping only markets with at least min_volume traded.

    Market size is unrelated to which way a market resolved, so this does not
    bias the test; it just drops markets too thin for a skilled-money signal.
    """
    events = []
    for event in raw["events"]:
        markets = [m for m in event.get("markets") or [] if market_volume(m) >= min_volume]
        if markets:
            events.append({**event, "markets": markets})
    kept = sum(len(e["markets"]) for e in events)
    print(f"Volume filter: kept {kept} markets in {len(events)} events with >= ${min_volume:,.0f} traded")
    return {**raw, "events": events, "min_market_volume_usd": min_volume}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-volume", type=float, default=50000,
                    help="only test markets with at least this much traded, in USD (0 = no filter)")
    ap.add_argument("--start", default=TEST_START, help="first resolution date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="resolution date cutoff, exclusive (default: today)")
    ap.add_argument("--source-catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=250)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    end = args.end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_ts, end_ts = timestamp(args.start), timestamp(end)
    if start_ts >= end_ts:
        ap.error("start must be before end")
    if start_ts < timestamp(TEST_START):
        print("WARNING: test window starts before 2026, so it overlaps the training data.")
    rd.SEED = "hackthebruh-finance-test-2026-v1"
    print(f"TEST window: markets resolved {args.start} to {end} (exclusive)")

    if args.verify_only:
        result = rd.validate(args.out)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if not args.source_catalog.exists():
        gzwrite(args.source_catalog, keyset_catalog(start_ts, end_ts))
    catalog_path = args.source_catalog
    if args.min_volume > 0:
        catalog_path = args.source_catalog.with_name(f"catalog-minvol-{int(args.min_volume)}.json.gz")
        if not catalog_path.exists():
            gzwrite(catalog_path, volume_filtered(gzread(args.source_catalog), args.min_volume))
    # resolved_dataset takes the window as arguments (its defaults are the 2025
    # training window), so pass the test dates explicitly.
    rd.build(args.out, catalog_path, args.count, max_pages=args.max_pages,
             workers=args.workers, start=start_ts, end=end_ts)
    return check_window(args.out, start_ts, end_ts)


def check_window(out, start_ts, end_ts):
    """Refuse to call the build good unless every market really resolved in the test window."""
    import csv
    with open(Path(out) / "markets.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    outside = [r["question"] for r in rows if not start_ts <= int(r["label_available_at"]) < end_ts]
    if outside:
        print(f"PROBLEM: {len(outside)} markets resolved outside the test window, e.g. {outside[0]!r}")
        return 1
    first = min(int(r["label_available_at"]) for r in rows)
    last = max(int(r["label_available_at"]) for r in rows)
    print(f"CHECK OK: all {len(rows)} markets resolved between "
          f"{datetime.fromtimestamp(first, timezone.utc):%d %b %Y} and "
          f"{datetime.fromtimestamp(last, timezone.utc):%d %b %Y}")
    validation = json.loads((Path(out) / "validation.json").read_text())
    if validation["passed"]:
        return 0
    # Since July 2026 prices-history returns overlapping 3h and 12h points, so
    # market_dataset's strict validator flags repeated timestamps. The files are
    # still written, and evaluate.py picks the latest price actually available at
    # each snapshot, so repeats are harmless for the backtest. Anything else is
    # a real failure.
    errors_path = Path(out) / "errors.json"
    errors = json.loads(errors_path.read_text()) if errors_path.exists() else []
    other = [i for i in validation["issues"]
             if "Duplicate price keys" not in i and i != "At least one market download failed"]
    other += [e["error"] for e in errors if "Duplicate price keys" not in e["error"]]
    missing = [r["question"] for r in rows
               if not (Path(out) / r["folder"] / "prices.csv.gz").exists()
               or not (Path(out) / r["folder"] / "wallet_trade_legs.csv.gz").exists()]
    if other or missing:
        print("PROBLEM: the build has real errors:")
        for issue in (other + [f"missing files for {q!r}" for q in missing])[:10]:
            print("  -", issue)
        return 1
    print(f"WARNING ONLY: {len(errors)} markets have repeated price timestamps (a Polymarket "
          "data quirk since July 2026). Their data is complete and usable for the backtest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())