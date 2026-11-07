"""Collect 100 settled finance markets from distinct Gamma parent events."""

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .client import Client, DATA
from .dataset import dump, gzread, gzwrite, read_table, subfield, table
from .market_dataset import build as build_market, validate as validate_market
from .research import array, iso, now, timestamp

DEFAULT_OUT = Path("datasets/finance/resolved-100-2025/v1")
DEFAULT_CATALOG = Path("data/archive/finance-2025-v1/v1/raw/catalog.json.gz")
START = timestamp("2025-08-01")
END = timestamp("2026-01-01")
SEED = "hackthebruh-finance-resolved-v1"


def parse_time(value):
    return int(value) if str(value).isdigit() else timestamp(value)


def economic_cluster(market, event):
    """Conservative family grouping beyond Gamma IDs; not a claim of independence."""
    title = event.get("title", "")
    question = market.get("question", "")
    text = f"{title} {question}".lower()
    closed = datetime.fromtimestamp(timestamp(market["closedTime"]), timezone.utc)
    ticker = re.search(r"\(([A-Z.]{1,7})\)", title + " " + question)
    if ticker and not any(term in text for term in ("earnings", "say during", "revenue")):
        # Competing weekly-close and above/below ladders share an asset and week.
        year, week, _ = closed.isocalendar()
        return f"asset-week:{ticker.group(1)}:{year}-{week:02}"
    if "largest company" in text or "largest companies" in text:
        return "company-rank:" + str(market.get("endDate", market["closedTime"]))[:7]
    if "ipo" in text:
        source = question if title.lower().strip().startswith("ipos") else title
        match = re.search(r"^(?:will\s+)?(.+?)\s+(?:ipo|have an ipo|complete an ipo)", source, re.I)
        if match:
            subject = re.sub(r"\b(will|inc|industries|corporation|complete|an|have|the)\b", "", match.group(1), flags=re.I)
            subject = re.sub(r"[^a-z0-9]", "", subject.lower())
            return "ipo:" + subject
    if any(term in text for term in ("fed decision", "fed rate", "dissent at the next fed")):
        return "fomc:" + closed.date().isoformat()
    acquisition = re.search(r"(?:acquire\s+)(.+?)(?:\s+by\b|\s+before\b|\?|$)", question, re.I)
    if not acquisition:
        acquisition = re.search(r"^(?:will\s+)?(.+?)\s+be acquired", question, re.I)
    if acquisition:
        subject = re.sub(r"[^a-z0-9]", "", acquisition.group(1).lower())
        return "acquisition:" + subject
    return "gamma-event:" + str(event["id"])


def candidates(catalog, minimum_days=7):
    rows, seen = [], set()
    for event in catalog["events"]:
        for market in event.get("markets", []):
            if not (market.get("closed") and market.get("umaResolutionStatus") == "resolved"
                    and array(market.get("outcomes")) == ["Yes", "No"]
                    and sorted(array(market.get("outcomePrices")))):
                continue
            if sorted(map(float, array(market.get("outcomePrices")))) != [0.0, 1.0]:
                continue
            opened = market.get("startDate") or market.get("createdAt")
            closed = market.get("closedTime")
            tokens = array(market.get("clobTokenIds"))
            condition = market.get("conditionId")
            if not opened or not closed or len(tokens) != 2 or not condition or condition in seen:
                continue
            opened, closed = timestamp(opened), timestamp(closed)
            if not START <= closed < END or closed - opened < minimum_days * 86400:
                continue
            seen.add(condition)
            order = hashlib.sha256(f"{SEED}:{event['id']}:{condition}".encode()).hexdigest()
            rows.append({"market": market, "event": {k: v for k, v in event.items() if k != "markets"},
                         "subfield": subfield(market.get("question", "")), "selection_order": order,
                         "economic_cluster_id": economic_cluster(market, event)})
    return rows


def verified_resolution(market, resolution):
    if resolution.get("status") != "resolved" or resolution.get("condition_id") != market.get("conditionId"):
        return None
    if resolution.get("payouts") is not None:
        payout = resolution["payouts"]
        if payout not in ([1000000, 0], [0, 1000000]):
            return None
        yes = int(payout[0] == 1000000)
    else:
        # UMA binary prices are fixed-point 1e18. Fractional/unknown payouts are excluded.
        price = resolution.get("price")
        if price not in ("0", "1000000000000000000"):
            return None
        yes = int(price == "1000000000000000000")
    if list(map(float, array(market.get("outcomePrices")))) != [float(yes), float(1 - yes)]:
        return None
    observed = resolution.get("resolved_at") or resolution.get("last_update_timestamp")
    if not observed:
        return None
    # Conservative label timestamp when the legacy lifecycle lacks resolved_at.
    label_time = max(parse_time(observed), timestamp(market["closedTime"]))
    if not START <= label_time < END:
        return None
    return {"yes_outcome": yes, "label_available_at": label_time,
            "label_available_at_utc": iso(label_time),
            "timestamp_basis": "max(Gamma closedTime, resolved_at or resolved lifecycle last_update)",
            "was_disputed": resolution.get("was_disputed"), "rules_updated": resolution.get("new_version_q")}


def select_verified(root, raw, count, minimum_days):
    pool = candidates(raw, minimum_days)
    buckets = defaultdict(list)
    for row in sorted(pool, key=lambda row: row["selection_order"]):
        buckets[row["subfield"]].append(row)
    ordered = []
    while any(buckets.values()):
        for field in sorted(buckets):
            if buckets[field]:
                ordered.append(buckets[field].pop(0))
    chosen, used_events, used_clusters, rejection_counts = [], set(), set(), Counter()
    client = Client()
    requests = []
    for offset in range(0, len(ordered), 20):
        batch = ordered[offset:offset + 20]
        response = client.get(DATA, "/v2/resolutions", condition=",".join(r["market"]["conditionId"] for r in batch))
        requests.append(response)
        resolved = {r.get("condition_id"): r for r in response["data"]}
        for row in batch:
            market = row["market"]
            event_id = row["event"]["id"]
            if event_id in used_events:
                rejection_counts["same_parent_event"] += 1
                continue
            if row["economic_cluster_id"] in used_clusters:
                rejection_counts["same_economic_family"] += 1
                continue
            resolution = resolved.get(market["conditionId"], {})
            label = verified_resolution(market, resolution)
            if not label:
                rejection_counts["unverified_or_out_of_window_resolution"] += 1
                continue
            chosen.append({**row, "resolution": resolution, "label": label})
            used_events.add(event_id)
            used_clusters.add(row["economic_cluster_id"])
            if len(chosen) == count:
                break
        if len(chosen) == count:
            break
    if len(chosen) != count:
        raise ValueError(f"Only {len(chosen)} eligible distinct parent events; requested {count}")
    gzwrite(root / "raw" / "selection.json.gz", {"selected": chosen, "resolution_responses": requests,
                                                "candidate_markets": len(pool), "rejections": dict(rejection_counts),
                                                "catalog_collected_at": raw["collected_at"], "catalog_query": raw["query"]})
    return chosen


def collect_one(root, chosen, max_pages, cache_source=None):
    market, event, label = chosen["market"], chosen["event"], chosen["label"]
    path = root / "markets" / market["id"]
    if not path.exists() and cache_source and (cache_source / "markets" / market["id"]).exists():
        shutil.copytree(cache_source / "markets" / market["id"], path)
    url = f"https://polymarket.com/event/{event['slug']}/{market['slug']}"
    if not (path / "config.json").exists():
        gzwrite(path / "raw" / "market.json.gz", {**market, "events": [event]})
        opened = timestamp(market.get("createdAt") or market["startDate"])
        dump(path / "config.json", {"schema_version": 1, "source_url": url,
                                   "condition_id": market["conditionId"], "start": opened // 86400 * 86400,
                                   "end_exclusive": label["label_available_at"] + 1, "bucket_seconds": 10800,
                                   "max_pages_per_feed": max_pages,
                                   "trade_feeds": {"trades": "taker_only=true", "wallet_trade_legs": "taker_only=false"}})
    manifest = build_market(path, url, max_pages)
    result = validate_market(path)
    if not result["passed"]:
        raise ValueError(f"Market {market['id']} validation failed: {result['issues'][:3]}")
    return manifest


def build(root, source_catalog, count=100, minimum_days=7, max_pages=250, workers=3, cache_source=None):
    root.mkdir(parents=True, exist_ok=True)
    settings = {"count": count, "resolution_start": START, "resolution_end_exclusive": END,
                "minimum_trading_lifetime_days": minimum_days, "selection_seed": SEED,
                "max_pages_per_feed": max_pages, "one_market_per_gamma_event": True,
                "economic_grouping_version": 1}
    if (root / "config.json").exists() and json.loads((root / "config.json").read_text()) != settings:
        raise ValueError("Output settings differ; use a new snapshot directory")
    dump(root / "config.json", settings)
    selection_path = root / "raw" / "selection.json.gz"
    discovery_path = root / "raw" / "discovery.json.gz"
    if source_catalog.exists() and not discovery_path.exists():
        discovery_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_catalog, discovery_path)
    if selection_path.exists():
        chosen = gzread(selection_path)["selected"]
    else:
        if not source_catalog.exists():
            # Rebuild the documented discovery input without relying on local archives.
            from .dataset import catalog
            gzwrite(discovery_path, catalog(Client(), 10000))
            source_catalog = discovery_path
        chosen = select_verified(root, gzread(source_catalog), count, minimum_days)
    print(f"SELECTED {len(chosen)} markets from {len({r['event']['id'] for r in chosen})} parent events", flush=True)
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(collect_one, root, row, max_pages, cache_source): row for row in chosen}
        for future in as_completed(futures):
            row = futures[future]
            market_id = row["market"]["id"]
            try:
                results[market_id] = future.result()
                print(f"COMPLETE {len(results)}/{count}: {market_id}", flush=True)
            except Exception as error:
                errors.append({"market_id": market_id, "error": str(error)})
                print(f"FAILED {market_id}: {error}", flush=True)
    dump(root / "errors.json", errors)
    market_rows, wallet_index, coverages = [], {}, []
    for row in sorted(chosen, key=lambda r: r["label"]["label_available_at"]):
        market, event, label = row["market"], row["event"], row["label"]
        market_id = market["id"]
        market_rows.append({"market_id": market_id, "condition_id": market["conditionId"],
                            "event_id": event["id"], "event_title": event.get("title"),
                            "economic_cluster_id": row["economic_cluster_id"],
                            "question": market["question"], "subfield": row["subfield"],
                            "trading_start": market.get("startDate"), "scheduled_end_date": market.get("endDate"),
                            **label, "folder": f"markets/{market_id}"})
        if market_id not in results:
            continue
        manifest = results[market_id]
        counts = manifest["counts"]
        coverages.append({"market_id": market_id, **counts,
                          "all_feeds_pagination_exhausted": manifest["all_feeds_pagination_exhausted"]})
        for wallet in read_table(root / "markets" / market_id / "wallets.csv"):
            address = wallet["wallet"]
            entry = wallet_index.setdefault(address, {"wallet": address, "observed_markets": 0,
                "taker_trade_rows": 0, "wallet_activity_rows": 0,
                "first_seen": int(wallet["first_seen"]), "last_seen": int(wallet["last_seen"])})
            entry["observed_markets"] += 1
            entry["taker_trade_rows"] += int(wallet["taker_trade_rows"])
            entry["wallet_activity_rows"] += int(wallet["market_trade_leg_rows"])
            entry["first_seen"] = min(entry["first_seen"], int(wallet["first_seen"]))
            entry["last_seen"] = max(entry["last_seen"], int(wallet["last_seen"]))
    table(root / "markets.csv", market_rows, list(market_rows[0]))
    table(root / "wallets.csv", [wallet_index[k] for k in sorted(wallet_index)],
          ["wallet", "observed_markets", "taker_trade_rows", "wallet_activity_rows", "first_seen", "last_seen"])
    table(root / "coverage.csv", coverages, list(coverages[0]) if coverages else ["market_id"])
    total = {"markets_selected": len(chosen), "markets_downloaded": len(results),
             "distinct_parent_events": len({r["event"]["id"] for r in chosen}),
             "distinct_economic_groups": len({r["economic_cluster_id"] for r in chosen}), "wallets": len(wallet_index),
             "taker_trade_rows": sum(r["taker_trade_rows"] for r in coverages),
             "wallet_activity_rows": sum(r["wallet_trade_leg_rows"] for r in coverages),
             "price_points": sum(r["price_points"] for r in coverages), "errors": len(errors)}
    manifest = {"dataset": "finance-resolved-100-2025-v1", "built_at": now(), "settings": settings,
                "counts": total, "subfields": dict(Counter(r["subfield"] for r in chosen)),
                "selection": "Seeded hash order and round-robin title-based subfields, one market per parent event. "
                             "Only verified binary outcomes; actual conservative label timestamps inside Aug-Dec 2025; "
                             "at least seven days of reported trading lifetime before closure. No selection on winner, volume or P&L.",
                "independence": "One per Gamma event and heuristic economic group. Asset-week price ladders, "
                                "IPO/acquisition families and same-day Fed decisions are grouped across IDs. "
                                "These rules do not establish statistical independence; common news and aliases remain.",
                "wallet_scope": "All wallet addresses returned in maker+taker feeds for selected markets. "
                                "Not all platform wallets, lifetime histories, or skilled/unskilled labels.",
                "files": []}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path not in (root / "manifest.json", root / "validation.json", root / "README.md", root / "overview.svg"):
            manifest["files"].append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    dump(root / "manifest.json", manifest)
    validation = validate(root)
    dump(root / "validation.json", validation)
    print("FINAL " + json.dumps({"counts": total, "validation": validation}), flush=True)
    return manifest


def validate(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    problems = []
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            problems.append(f"Checksum mismatch: {item['path']}")
    rows = read_table(root / "markets.csv")
    if len(rows) != manifest["settings"]["count"] or len({r["event_id"] for r in rows}) != len(rows):
        problems.append("Expected one market per distinct parent event")
    if len({r["economic_cluster_id"] for r in rows}) != len(rows):
        problems.append("Repeated economic family")
    for row in rows:
        if not START <= int(row["label_available_at"]) < END or row["yes_outcome"] not in ("0", "1"):
            problems.append(f"Invalid label for {row['market_id']}")
        child = root / row["folder"]
        if not (child / "manifest.json").exists():
            problems.append(f"Missing market snapshot: {row['market_id']}")
        else:
            result = validate_market(child)
            if not result["passed"]:
                problems.append(f"Invalid market snapshot {row['market_id']}: {result['issues'][:2]}")
    if manifest["counts"]["errors"] or manifest["counts"]["markets_downloaded"] != len(rows):
        problems.append("At least one market download failed")
    return {"validated_at": now(), "passed": not problems, "issues": problems[:100],
            "payload_checksums_verified": len(manifest["files"]),
            "per_market_validations": manifest["counts"]["markets_downloaded"],
            "checks": ["payload SHA-256", "100 selected markets", "distinct parent event IDs",
                       "distinct heuristic economic families", "binary settled labels", "actual label timestamp window", "all downloads succeeded",
                       "per-market trade, price and wallet validation during collection"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--source-catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--cache-source", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        result = validate(args.out)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if min(args.count, args.max_pages, args.workers) < 1:
        parser.error("limits must be positive")
    build(args.out, args.source_catalog, args.count, max_pages=args.max_pages, workers=args.workers,
          cache_source=args.cache_source)
    return 0 if json.loads((args.out / "validation.json").read_text())["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
