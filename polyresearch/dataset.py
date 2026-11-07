"""Build a versioned, auditable finance dataset from public Polymarket APIs.

Run with: python -m polyresearch.dataset --out datasets/finance/2025-08_2025-12/v1
Existing successful downloads are reused so an interrupted build can resume.
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .client import ApiError, Client, GAMMA
from .research import array, collect_prices, collect_trades, iso, now, timestamp

START = timestamp("2025-08-01")
END = timestamp("2026-01-01")


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def gzwrite(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Stable gzip header: no collection-machine path, no varying compression timestamp.
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(json.dumps(value, separators=(",", ":"), allow_nan=False).encode())


def gzread(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def table(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        handle = gzip.open(path, "wt", newline="", encoding="utf-8")
    else:
        handle = path.open("w", newline="", encoding="utf-8")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def subfield(question):
    text = question.lower()
    if re.search(r"\b(treasury|yield|fed|interest rate|inflation|recession|gdp)\b", text):
        return "rates_and_macro"
    if re.search(r"\b(gold|silver|oil|crude|copper|commodity|commodities)\b", text):
        return "commodities"
    if re.search(r"\b(etf|stablecoin|bitcoin reserve)\b", text):
        return "etfs_and_digital_finance"
    if re.search(r"\b(ipo|acquired|acquire|acquisition|merger)\b", text):
        return "ipos_and_deals"
    return "equities_and_corporate"


def catalog(client, max_events):
    tag = client.get(GAMMA, "/tags/slug/finance")
    events, seen = [], set()
    exhausted = False
    params = {"tag_id": tag["id"], "order": "id", "ascending": True,
              "start_date_max": iso(END), "end_date_min": iso(START)}
    while len(events) < max_events:
        limit = min(100, max_events - len(events))
        batch = client.get(GAMMA, "/events", **params, limit=limit, offset=len(events))
        if not isinstance(batch, list):
            raise ApiError("Unexpected event schema")
        for event in batch:
            if event["id"] in seen:
                raise ApiError("Repeated event during offset pagination; rebuild catalog")
            seen.add(event["id"])
        events.extend(batch)
        print(f"Catalog: {len(events)} events", flush=True)
        if len(batch) < limit:
            exhausted = True
            break
    return {"collected_at": now(), "tag": tag, "query": params,
            "events": events, "pagination_exhausted": exhausted}


def catalog_rows(raw):
    markets = {}
    outcomes = []
    for event in raw["events"]:
        for market in event.get("markets", []):
            condition = market.get("conditionId")
            opened = market.get("startDate") or market.get("createdAt")
            ended = market.get("endDate")
            if not condition or (opened and timestamp(opened) >= END) or (ended and timestamp(ended) < START):
                continue
            if condition in markets:
                continue
            row = {"condition_id": condition, "market_id": market["id"],
                   "event_id": event["id"], "event_title": event.get("title", ""),
                   "question": market.get("question", ""), "slug": market.get("slug", ""),
                   "subfield": subfield(market.get("question", "")),
                   "start_date": opened, "end_date": ended,
                   "closed_now": market.get("closed"),
                   "resolved_status_now": market.get("umaResolutionStatus"),
                   "closed_time_now": market.get("closedTime"),
                   "description": market.get("description"),
                   "resolution_source": market.get("resolutionSource"),
                   "tags_now": "|".join(t.get("slug", "") for t in event.get("tags", [])),
                   "collected_at": raw["collected_at"]}
            markets[condition] = row
            labels = array(market.get("outcomes"))
            tokens = array(market.get("clobTokenIds"))
            prices = array(market.get("outcomePrices"))
            for i, label in enumerate(labels):
                outcomes.append({"condition_id": condition, "outcome_index": i, "outcome": label,
                                 "token_id": tokens[i] if i < len(tokens) else "",
                                 "price_now": prices[i] if i < len(prices) else ""})
    return list(markets.values()), outcomes


def select(markets, outcomes, per_field):
    tokens = defaultdict(list)
    for outcome in outcomes:
        tokens[outcome["condition_id"]].append(outcome)
    buckets = defaultdict(list)
    for market in markets:
        legs = tokens[market["condition_id"]]
        if len(legs) == 2 and {r["outcome"].lower() for r in legs} == {"yes", "no"} and all(r["token_id"] for r in legs):
            buckets[market["subfield"]].append(market)
    selected = []
    for field in sorted(buckets):
        # Prioritize full-window candidates, then earlier start and ID. No prices,
        # profits, volume or winning outcomes are used to choose markets.
        candidates = sorted(buckets[field], key=lambda m: (
            not (m["start_date"] and timestamp(m["start_date"]) <= START and
                 m["end_date"] and timestamp(m["end_date"]) >= END - 86400),
            timestamp(m["start_date"]) if m["start_date"] else END,
            int(m["market_id"])))
        counts = Counter()
        chosen = []
        for market in candidates:
            if counts[market["event_id"]] < 2:
                chosen.append(market)
                counts[market["event_id"]] += 1
            if len(chosen) >= per_field:
                break
        selected.extend(chosen)
    return selected


def download_market(root, market, outcomes, max_pages):
    client = Client(timeout=30, retries=3)
    condition = market["condition_id"]
    folder = root / "raw" / "markets" / market["market_id"]
    trades_path = folder / "trades.json.gz"
    if not trades_path.exists():
        gzwrite(trades_path, collect_trades(client, condition, START, END, max_pages))
    trades = gzread(trades_path)
    prices = []
    for outcome in outcomes:
        path = folder / f"prices-{outcome['outcome_index']}.json.gz"
        if not path.exists():
            gzwrite(path, collect_prices(client, outcome["token_id"], START, END, 10800, max_pages))
        result = gzread(path)
        prices.append((outcome, result))
    return market, trades, prices


TRADE_FIELDS = ["condition_id", "timestamp", "timestamp_utc", "wallet", "side", "outcome",
                "token_id", "size_shares", "price", "notional_usdc", "transaction_hash"]
PRICE_FIELDS = ["condition_id", "token_id", "outcome", "timestamp", "timestamp_utc", "price",
                "resolution_seconds", "available_at", "available_at_utc"]


def build(root, per_field=6, max_events=10000, max_pages=100, workers=4):
    root.mkdir(parents=True, exist_ok=True)
    config = {"start": START, "end_exclusive": END, "per_subfield": per_field,
              "max_events": max_events, "max_trade_pages_per_market": max_pages,
              "bucket_seconds": 10800, "market_taker_only": True, "schema_version": 1}
    config_path = root / "config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("Existing release has a different configuration; choose a new output path")
    dump(config_path, config)
    raw_path = root / "raw" / "catalog.json.gz"
    if not raw_path.exists():
        gzwrite(raw_path, catalog(Client(), max_events))
    raw = gzread(raw_path)
    markets, outcomes = catalog_rows(raw)
    selected = select(markets, outcomes, per_field)
    table(root / "markets.csv", markets, list(markets[0]) if markets else ["condition_id"])
    table(root / "outcomes.csv", outcomes, ["condition_id", "outcome_index", "outcome", "token_id", "price_now"])
    table(root / "sample.csv", selected, ["condition_id", "market_id", "event_id", "subfield", "slug", "question"])
    print(f"Catalog: {len(markets)} markets; downloading {len(selected)} sample markets", flush=True)
    by_condition = defaultdict(list)
    for outcome in outcomes:
        by_condition[outcome["condition_id"]].append(outcome)
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_market, root, market, by_condition[market["condition_id"]], max_pages): market
                   for market in selected}
        for future in as_completed(futures):
            market = futures[future]
            try:
                result = future.result()
                results[market["condition_id"]] = result
                print(f"Downloaded {market['slug']}: {len(result[1]['trades'])} window trades", flush=True)
            except Exception as error:
                errors.append({"condition_id": market["condition_id"], "error": str(error)})
                print(f"FAILED {market['slug']}: {error}", flush=True)
    trade_rows, price_rows, coverage = [], [], []
    wallets = {}
    for condition in sorted(results):
        market, trades, prices = results[condition]
        rows = trades["trades"]
        for row in rows:
            wallet = row["proxy_wallet"].lower()
            t = int(row["timestamp"])
            trade_rows.append({"condition_id": condition, "timestamp": t, "timestamp_utc": iso(t),
                               "wallet": wallet, "side": row["side"], "outcome": row["outcome"],
                               "token_id": row["token_id"], "size_shares": row["size"], "price": row["price"],
                               "notional_usdc": row["size"] * row["price"],
                               "transaction_hash": row.get("transaction_hash", "")})
            entry = wallets.setdefault(wallet, {"wallet": wallet, "sample_trade_rows": 0,
                                                "sample_first_seen": t, "sample_last_seen": t, "markets": set()})
            entry["sample_trade_rows"] += 1
            entry["sample_first_seen"] = min(entry["sample_first_seen"], t)
            entry["sample_last_seen"] = max(entry["sample_last_seen"], t)
            entry["markets"].add(condition)
        price_counts = Counter()
        for outcome, history in prices:
            for point in history["points"]:
                t = int(point["timestamp"])
                available = t + int(point["resolution_seconds"])
                price_rows.append({"condition_id": condition, "token_id": outcome["token_id"],
                                   "outcome": outcome["outcome"], "timestamp": t, "timestamp_utc": iso(t),
                                   "price": point["price"], "resolution_seconds": point["resolution_seconds"],
                                   "available_at": available, "available_at_utc": iso(available)})
                price_counts[outcome["outcome"]] += 1
        coverage.append({"condition_id": condition, "slug": market["slug"], "subfield": market["subfield"],
                         "trade_rows": len(rows), "trade_pages": trades["pages_fetched"],
                         "trade_pagination_exhausted": trades["pagination_exhausted"],
                         "earliest_scanned_trade": trades["earliest_scanned"],
                         "latest_scanned_trade": trades["latest_scanned"],
                         "first_window_trade": min((r["timestamp"] for r in rows), default=None),
                         "last_window_trade": max((r["timestamp"] for r in rows), default=None),
                         "yes_price_points": price_counts["Yes"], "no_price_points": price_counts["No"],
                         "price_pagination_exhausted": all(p[1]["pagination_exhausted"] for p in prices)})
    trade_rows.sort(key=lambda r: (r["condition_id"], r["timestamp"], r["transaction_hash"]))
    price_rows.sort(key=lambda r: (r["condition_id"], r["token_id"], r["timestamp"]))
    table(root / "trades.csv.gz", trade_rows, TRADE_FIELDS)
    table(root / "prices.csv.gz", price_rows, PRICE_FIELDS)
    wallet_rows = [{**{k: v for k, v in entry.items() if k != "markets"},
                    "sample_distinct_markets": len(entry["markets"])} for _, entry in sorted(wallets.items())]
    table(root / "wallets.csv", wallet_rows, ["wallet", "sample_trade_rows", "sample_distinct_markets",
                                            "sample_first_seen", "sample_last_seen"])
    table(root / "coverage.csv", coverage, list(coverage[0]) if coverage else ["condition_id"])
    dump(root / "errors.json", errors)
    manifest = {"dataset": "polymarket-finance-2025-v1", "built_at": now(), "config": config,
                "catalog_collected_at": raw["collected_at"],
                "catalog_query": raw["query"], "catalog_pagination_exhausted": raw["pagination_exhausted"],
                "counts": {"catalog_events": len(raw["events"]), "catalog_markets": len(markets),
                           "catalog_outcomes": len(outcomes), "sample_markets_selected": len(selected),
                           "sample_markets_downloaded": len(results), "trade_rows": len(trade_rows),
                           "price_points": len(price_rows), "wallets": len(wallets), "download_errors": len(errors),
                           "trade_feeds_exhausted": sum(c["trade_pagination_exhausted"] for c in coverage)},
                "selection": f"Up to {per_field} per title-derived subfield; prioritize scheduled full-window overlap, "
                             "then earliest start and market ID; maximum two per event. "
                             "No profit, price, volume, winner or observed coverage used for selection.",
                "scope": "Finance-tagged event catalog filtered by event-date overlap, then child-market overlap; "
                         f"{len(selected)}-market non-random starter sample. Current tags and dates can be revised.",
                "wallets": "Wallet index is observed taker activity in this sample, not lifetime history or skill. "
                           "Historical profit enrichment and skill labels are not part of this release.",
                "sources": ["https://polymarket.com/finance", "https://gamma-api.polymarket.com/events",
                            "https://data-api.polymarket.com/v2/trades", "https://data-api.polymarket.com/v2/prices-history"],
                "files": []}
    # Manifest intentionally excludes its own digest; verify every listed payload.
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "validation.json", "README.md", "overview.svg"):
            manifest["files"].append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    dump(root / "manifest.json", manifest)
    validation = validate(root)
    dump(root / "validation.json", validation)
    print(json.dumps({"counts": manifest["counts"], "validation": validation}, indent=2), flush=True)
    return manifest


def read_table(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate(root):
    manifest = json.loads((root / "manifest.json").read_text())
    issues = []
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            issues.append(f"Checksum mismatch: {item['path']}")
    markets = {m["condition_id"] for m in read_table(root / "markets.csv")}
    sampled = {m["condition_id"] for m in read_table(root / "sample.csv")}
    outcomes = {(r["condition_id"], r["token_id"]): r["outcome"] for r in read_table(root / "outcomes.csv")}
    trades = read_table(root / "trades.csv.gz")
    prices = read_table(root / "prices.csv.gz")
    wallets = {w["wallet"] for w in read_table(root / "wallets.csv")}
    for name, rows in [("trade", trades), ("price", prices)]:
        for i, row in enumerate(rows):
            if row["condition_id"] not in markets or row["condition_id"] not in sampled:
                issues.append(f"Invalid {name} market at row {i}")
            key = (row["condition_id"], row["token_id"])
            if key not in outcomes or row["outcome"] != outcomes.get(key):
                issues.append(f"Invalid {name} outcome at row {i}")
            if not START <= int(row["timestamp"]) < END:
                issues.append(f"Out-of-window {name} row {i}")
            if not math.isfinite(float(row["price"])) or not 0 <= float(row["price"]) <= 1:
                issues.append(f"Invalid {name} price at row {i}")
    for i, row in enumerate(trades):
        if row["wallet"] not in wallets or not re.fullmatch(r"0x[0-9a-f]{40}", row["wallet"]):
            issues.append(f"Invalid wallet at trade {i}")
        if (row["side"] not in ("BUY", "SELL") or not math.isfinite(float(row["size_shares"]))
                or float(row["size_shares"]) < 0):
            issues.append(f"Invalid trade at row {i}")
    for i, row in enumerate(prices):
        if int(row["available_at"]) != int(row["timestamp"]) + int(row["resolution_seconds"]):
            issues.append(f"Invalid price availability at row {i}")
    counts = manifest["counts"]
    if len(trades) != counts["trade_rows"] or len(prices) != counts["price_points"] or len(wallets) != counts["wallets"]:
        issues.append("Manifest counts do not match tables")
    if counts["download_errors"] or counts["sample_markets_downloaded"] != counts["sample_markets_selected"]:
        issues.append("Sample downloads did not all succeed")
    coverage = read_table(root / "coverage.csv")
    trade_counts = Counter(r["condition_id"] for r in trades)
    price_counts = Counter((r["condition_id"], r["outcome"].lower()) for r in prices)
    if {r["condition_id"] for r in coverage} != sampled:
        issues.append("Coverage does not match selected markets")
    for row in coverage:
        condition = row["condition_id"]
        if (int(row["trade_rows"]) != trade_counts[condition]
                or int(row["yes_price_points"]) != price_counts[condition, "yes"]
                or int(row["no_price_points"]) != price_counts[condition, "no"]):
            issues.append(f"Coverage counts differ for {condition}")
    # Count suspicious duplicates without silently dropping potentially legitimate fills.
    trade_duplicates = len(trades) - len({tuple(r[k] for k in TRADE_FIELDS) for r in trades})
    price_duplicates = len(prices) - len({(r["token_id"], r["timestamp"]) for r in prices})
    if price_duplicates:
        issues.append(f"Duplicate price keys: {price_duplicates}")
    return {"validated_at": now(), "passed": not issues, "issues": issues[:100],
            "issue_count": len(issues), "payload_checksums_verified": len(manifest["files"]),
            "trade_identical_rows_retained": trade_duplicates, "duplicate_price_keys": price_duplicates,
            "checks": ["SHA-256 payloads", "foreign keys and token/outcome mapping", "UTC date bounds",
                       "prices in [0,1]", "wallet format and references", "trade side and size",
                       "price availability timestamps", "manifest row counts", "price key uniqueness",
                       "all selected downloads succeeded", "per-market coverage counts"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("datasets/finance/2025-08_2025-12/v1"))
    parser.add_argument("--per-subfield", type=int, default=6)
    parser.add_argument("--max-events", type=int, default=10000)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        result = validate(args.out)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if min(args.per_subfield, args.max_events, args.max_pages, args.workers) < 1:
        parser.error("limits and workers must be positive")
    build(args.out, args.per_subfield, args.max_events, args.max_pages, args.workers)
    return 0 if json.loads((args.out / "validation.json").read_text())["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
