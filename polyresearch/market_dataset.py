"""Build one market's dataset from its exact Polymarket URL."""

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .client import ApiError, Client, GAMMA, pages
from .dataset import PRICE_FIELDS, TRADE_FIELDS, dump, gzread, gzwrite, read_table, table
from .research import array, collect_prices, collect_trades, iso, now, timestamp

MARKET_URL = ("https://polymarket.com/event/anthropic-ipo-closing-market-cap-higher-strikes/"
              "will-anthropics-market-cap-be-between-1pt25t-and-1pt5t-at-market-close-on-ipo-day")
DEFAULT_OUT = Path("datasets/finance/anthropic-ipo-1_25t-1_5t/v1")


def url_parts(url):
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme != "https" or parsed.hostname not in ("polymarket.com", "www.polymarket.com"):
        raise ValueError("Expected an https://polymarket.com market URL")
    if len(parts) != 3 or parts[0] != "event" or not all(parts):
        raise ValueError("Use the URL for one market: /event/EVENT_SLUG/MARKET_SLUG")
    return parts[1], parts[2]


def resolve(client, url):
    event_slug, slug = url_parts(url)
    rows = client.get(GAMMA, "/markets", slug=slug)
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("slug") != slug:
        raise ApiError("The URL did not resolve to exactly one matching market")
    market = rows[0]
    if event_slug not in {event.get("slug") for event in market.get("events", [])}:
        raise ApiError("Resolved market does not belong to the URL's event")
    if not market.get("conditionId"):
        raise ApiError("Resolved market has no condition ID")
    return market


def normalize_trades(rows):
    return sorted([{
        "condition_id": row["condition_id"], "timestamp": int(row["timestamp"]),
        "timestamp_utc": iso(int(row["timestamp"])), "wallet": row["proxy_wallet"].lower(),
        "side": row["side"], "outcome": row["outcome"], "token_id": row["token_id"],
        "size_shares": row["size"], "price": row["price"],
        "notional_usdc": row["size"] * row["price"], "transaction_hash": row.get("transaction_hash", ""),
    } for row in rows], key=lambda r: (r["timestamp"], r["transaction_hash"], r["wallet"]))


def summarize_wallets(legs, takers):
    taker_counts = Counter(r["wallet"] for r in takers)
    wallets = {}
    for row in legs:
        wallet = row["wallet"]
        observed_at = int(row["timestamp"])
        notional = float(row["notional_usdc"])
        entry = wallets.setdefault(wallet, {
            "wallet": wallet, "market_trade_leg_rows": 0, "taker_trade_rows": taker_counts[wallet],
            "first_seen": observed_at, "last_seen": observed_at,
            "buy_notional_usdc": 0.0, "sell_notional_usdc": 0.0, "yes_signed_flow_usdc": 0.0,
        })
        entry["market_trade_leg_rows"] += 1
        entry["first_seen"] = min(entry["first_seen"], observed_at)
        entry["last_seen"] = max(entry["last_seen"], observed_at)
        entry["buy_notional_usdc" if row["side"] == "BUY" else "sell_notional_usdc"] += notional
        sign = (1 if row["outcome"].lower() == "yes" else -1) * (1 if row["side"] == "BUY" else -1)
        entry["yes_signed_flow_usdc"] += sign * notional
    return [wallets[key] for key in sorted(wallets)]


def build(root, url=MARKET_URL, max_pages=250):
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
        if config["source_url"] != url or config["max_pages_per_feed"] != max_pages:
            raise ValueError("Existing snapshot uses different settings; choose a new output directory")
        market = gzread(root / "raw" / "market.json.gz")
    else:
        market = resolve(Client(), url)
        # UTC day containing creation, to include any trading before startDate metadata.
        opened = timestamp(market.get("createdAt") or market["startDate"])
        config = {"schema_version": 1, "source_url": url, "condition_id": market["conditionId"],
                  "start": opened // 86400 * 86400,
                  "end_exclusive": int(datetime.now(timezone.utc).timestamp()),
                  "bucket_seconds": 10800, "max_pages_per_feed": max_pages,
                  "trade_feeds": {"trades": "taker_only=true", "wallet_trade_legs": "taker_only=false"}}
        gzwrite(root / "raw" / "market.json.gz", market)
        dump(config_path, config)
    start, end, condition = config["start"], config["end_exclusive"], config["condition_id"]
    labels, tokens = array(market["outcomes"]), array(market["clobTokenIds"])
    if len(tokens) != 2 or len(labels) != 2 or {label.lower() for label in labels} != {"yes", "no"}:
        raise ValueError("The first single-market dataset supports binary YES/NO markets")
    outcomes = [{"condition_id": condition, "outcome_index": i, "outcome": label,
                 "token_id": tokens[i]} for i, label in enumerate(labels)]
    print(f"Market: {market['question']}\nWindow: {iso(start)} to {iso(end)} (exclusive)", flush=True)

    def fetch(name):
        path = root / "raw" / f"{name}.json.gz"
        if path.exists():
            return gzread(path)
        client = Client()
        if name == "trades":
            result = collect_trades(client, condition, start, end, max_pages)
        elif name == "wallet_trade_legs":
            rows, raw, exhausted = pages(client, "/v2/trades", {
                "condition": condition, "taker_only": False, "limit": 1000,
            }, max_pages)
            result = {"collected_at": now(), "condition_id": condition, "start": start, "end": end,
                      "trades": [r for r in rows if start <= int(r["timestamp"]) < end],
                      "pagination_exhausted": exhausted, "pages_fetched": len(raw),
                      "raw_pages": raw, "rows_scanned": len(rows),
                      "warning": "Maker and taker rows; not unique executions. Do not sum as market volume."}
        else:
            i = int(name.split("-")[1])
            result = collect_prices(client, tokens[i], start, end, config["bucket_seconds"], max_pages)
        gzwrite(path, result)
        return result

    downloads = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch, name): name for name in ("trades", "wallet_trade_legs", "prices-0", "prices-1")}
        for job in as_completed(jobs):
            name = jobs[job]
            downloads[name] = job.result()
            count = len(downloads[name].get("trades", downloads[name].get("points", [])))
            print(f"Downloaded {name}: {count} rows; pagination exhausted: {downloads[name]['pagination_exhausted']}", flush=True)
    trades = normalize_trades(downloads["trades"]["trades"])
    legs = normalize_trades(downloads["wallet_trade_legs"]["trades"])
    price_rows, excluded = [], 0
    for i, outcome in enumerate(outcomes):
        for point in downloads[f"prices-{i}"]["points"]:
            t = int(point["timestamp"])
            available = t + int(point["resolution_seconds"])
            if available > end:
                excluded += 1
                continue
            price_rows.append({"condition_id": condition, "token_id": outcome["token_id"],
                               "outcome": outcome["outcome"], "timestamp": t, "timestamp_utc": iso(t),
                               "price": point["price"], "resolution_seconds": point["resolution_seconds"],
                               "available_at": available, "available_at_utc": iso(available)})
    price_rows.sort(key=lambda row: (row["token_id"], row["timestamp"]))
    wallets = summarize_wallets(legs, trades)
    table(root / "trades.csv.gz", trades, TRADE_FIELDS)
    table(root / "wallet_trade_legs.csv.gz", legs, TRADE_FIELDS)
    table(root / "prices.csv.gz", price_rows, PRICE_FIELDS)
    table(root / "wallets.csv", wallets, ["wallet", "market_trade_leg_rows", "taker_trade_rows", "first_seen", "last_seen",
                                         "buy_notional_usdc", "sell_notional_usdc", "yes_signed_flow_usdc"])
    table(root / "outcomes.csv", outcomes, ["condition_id", "outcome_index", "outcome", "token_id"])
    dump(root / "market.json", {"source_url": url, "market_id": market["id"], "condition_id": condition,
                                "event_id": market["events"][0]["id"], "slug": market["slug"],
                                "question": market["question"], "created_at": market.get("createdAt"),
                                "start_date": market.get("startDate"), "end_date": market.get("endDate"),
                                "closed_now": market.get("closed"), "description": market.get("description"),
                                "resolution_source": market.get("resolutionSource"), "outcomes": outcomes})
    coverage = []
    for name, result in sorted(downloads.items()):
        rows = result.get("trades", result.get("points", []))
        coverage.append({"feed": name, "pagination_exhausted": result["pagination_exhausted"],
                         "raw_window_rows": len(rows), "first_observation": min((r["timestamp"] for r in rows), default=None),
                         "last_observation": max((r["timestamp"] for r in rows), default=None)})
    table(root / "coverage.csv", coverage, ["feed", "pagination_exhausted", "raw_window_rows",
                                          "first_observation", "last_observation"])
    month_counts = Counter(row["timestamp_utc"][:7] for row in trades)
    manifest = {"dataset": "anthropic-ipo-1_25t-1_5t-v1", "built_at": now(), "config": config,
                "question": market["question"], "market_opened": market["startDate"],
                "counts": {"markets": 1, "outcomes": len(outcomes), "taker_trade_rows": len(trades),
                           "wallet_trade_leg_rows": len(legs), "price_points": len(price_rows),
                           "wallets": len(wallets), "price_points_excluded_not_yet_available": excluded},
                "taker_trade_rows_by_month": dict(sorted(month_counts.items())),
                "all_feeds_pagination_exhausted": all(r["pagination_exhausted"] for r in downloads.values()),
                "scope": "Exactly the linked binary market; no sibling valuation brackets. Lifetime observations "
                         "up to an exclusive frozen snapshot cutoff, reconstructed from the API.",
                "wallet_scope": "Observed maker and taker activity in this market only. Not lifetime wallet profit "
                                "or skill; historical wallet enrichment comes next. Roles are not exposed per row.",
                "sources": [url, "https://gamma-api.polymarket.com/markets",
                            "https://data-api.polymarket.com/v2/trades", "https://data-api.polymarket.com/v2/prices-history"],
                "files": []}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "validation.json", "README.md", "overview.svg"):
            manifest["files"].append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    dump(root / "manifest.json", manifest)
    validation = validate(root)
    dump(root / "validation.json", validation)
    print(json.dumps({"counts": manifest["counts"], "validation": validation}, indent=2), flush=True)
    return manifest


def validate(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    config, issues = manifest["config"], []
    start, end, condition = config["start"], config["end_exclusive"], config["condition_id"]
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            issues.append(f"Checksum mismatch: {item['path']}")
    outcomes = {row["token_id"]: row["outcome"] for row in read_table(root / "outcomes.csv")}
    wallets = {row["wallet"]: row for row in read_table(root / "wallets.csv")}
    tables = {name: read_table(root / name) for name in ("trades.csv.gz", "wallet_trade_legs.csv.gz", "prices.csv.gz")}
    for name, rows in tables.items():
        for i, row in enumerate(rows):
            if row["condition_id"] != condition or outcomes.get(row["token_id"]) != row["outcome"]:
                issues.append(f"Wrong market/token/outcome: {name}:{i}")
            if not start <= int(row["timestamp"]) < end or not 0 <= float(row["price"]) <= 1:
                issues.append(f"Invalid date/price: {name}:{i}")
            if not math.isfinite(float(row["price"])):
                issues.append(f"Non-finite price: {name}:{i}")
            if "wallet" in row:
                size, price, cash = (float(row[key]) for key in ("size_shares", "price", "notional_usdc"))
                if (not math.isfinite(size) or size < 0 or row["side"] not in ("BUY", "SELL")
                        or not math.isclose(cash, size * price, rel_tol=1e-10, abs_tol=1e-10)):
                    issues.append(f"Invalid side/size/notional: {name}:{i}")
                if row["wallet"] not in wallets or not re.fullmatch(r"0x[0-9a-f]{40}", row["wallet"]):
                    issues.append(f"Invalid wallet: {name}:{i}")
            else:
                if (int(row["available_at"]) != int(row["timestamp"]) + int(row["resolution_seconds"])
                        or int(row["available_at"]) > end):
                    issues.append(f"Invalid availability: {name}:{i}")
    legs, takers = tables["wallet_trade_legs.csv.gz"], tables["trades.csv.gz"]
    counts = manifest["counts"]
    actual = {"taker_trade_rows": len(takers), "wallet_trade_leg_rows": len(legs),
              "price_points": len(tables["prices.csv.gz"]), "wallets": len(wallets)}
    if any(counts[key] != value for key, value in actual.items()):
        issues.append("Manifest counts do not match tables")
    # The two API walks lack a universal public fill ID, so compare multisets of all
    # execution fields rather than transaction hashes or assumed one-to-one matching.
    taker_keys = Counter(tuple(row[key] for key in TRADE_FIELDS) for row in takers)
    leg_keys = Counter(tuple(row[key] for key in TRADE_FIELDS) for row in legs)
    if taker_keys - leg_keys:
        issues.append("Taker execution rows are missing from the all-wallet feed")
    for row in summarize_wallets(legs, takers):
        saved = wallets.get(row["wallet"])
        for key, value in row.items():
            if saved is None or (key != "wallet" and not math.isclose(float(saved[key]), float(value), rel_tol=1e-10, abs_tol=1e-8)):
                issues.append(f"Wallet rollup mismatch: {row['wallet']}:{key}")
    prices = tables["prices.csv.gz"]
    price_duplicate_keys = len(prices) - len({(r["token_id"], r["timestamp"]) for r in prices})
    if price_duplicate_keys:
        issues.append(f"Duplicate price keys: {price_duplicate_keys}")
    if not manifest["all_feeds_pagination_exhausted"]:
        issues.append("At least one feed hit its page limit")
    return {"validated_at": now(), "passed": not issues, "issue_count": len(issues), "issues": issues[:100],
            "payload_checksums_verified": len(manifest["files"]),
            "identical_taker_rows_retained": sum(count - 1 for count in taker_keys.values()),
            "duplicate_price_keys": price_duplicate_keys,
            "checks": ["SHA-256 checksums", "exact market/token/outcome", "frozen UTC window", "valid prices",
                       "valid wallets and sides", "notional arithmetic", "price availability", "row counts",
                       "taker rows included in all-wallet feed", "wallet rollups", "unique price timestamps",
                       "pagination exhausted"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=MARKET_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error("--max-pages must be positive")
    try:
        if args.verify_only:
            result = validate(args.out)
            print(json.dumps(result, indent=2))
        else:
            build(args.out, args.url, args.max_pages)
            result = json.loads((args.out / "validation.json").read_text())
        return 0 if result["passed"] else 1
    except (ApiError, OSError, ValueError, KeyError) as error:
        print(f"Error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
