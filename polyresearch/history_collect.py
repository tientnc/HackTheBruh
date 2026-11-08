"""Collect thousands of resolved markets from before 2026, for rating wallets.

Lean version of resolved_dataset.py, built for scale: it keeps only what
polyresearch/backtest/tiers.py needs (every fill + the verified outcome), resumes
where it left off, and never uses a market resolved on or after the cutoff.

  1. Discover closed Yes/No markets with Gamma's /markets/keyset (most-traded first).
  2. Verify each outcome with Data API /v2/resolutions (same rules as resolved_dataset.py)
     and keep only labels available BEFORE the cutoff (default 1 Jan 2026).
  3. Download every fill (maker and taker) with /v2/trades?taker_only=false.
     Markets with more fills than --max-pages * 1000 are skipped, because a partial
     history would give wrong profits.
  4. Write markets.csv + markets/<id>/wallet_trade_legs.csv.gz (same columns as the
     repo's datasets), so tiers.py can read it directly.

Output goes to data/history/... by default, which .gitignore keeps out of git: 10,000
markets is several hundred MB. Commit the ratings, not this folder.

Public APIs, no key needed. Run from the repo root:
  python -m polyresearch.history_collect --count 10000
  python -m polyresearch.backtest.tiers --history data/history/pre-2026/v1 datasets/finance/resolved-100-2025/v1
"""

import argparse
import csv
import gzip
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .client import DATA, GAMMA, ApiError, Client, pages
from .dataset import subfield, table
from .market_dataset import normalize_trades
from .research import array, iso, timestamp
from .resolved_dataset import economic_cluster, verified_resolution

CUTOFF = timestamp("2026-01-01")
DEFAULT_OUT = Path("data/history/pre-2026/v1")
LEG_FIELDS = ["condition_id", "timestamp", "timestamp_utc", "wallet", "side", "outcome", "token_id",
              "size_shares", "price", "notional_usdc", "transaction_hash"]
MARKET_FIELDS = ["market_id", "condition_id", "event_id", "economic_cluster_id", "question", "subfield",
                 "yes_outcome", "label_available_at", "label_available_at_utc", "fills", "folder"]


def read_jsonl(path):
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, rows, lock=threading.Lock()):
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")


def usable(market, start, min_days):
    """Closed, resolved, plain Yes/No market that traded for long enough in the window."""
    if not (market.get("closed") and market.get("umaResolutionStatus") == "resolved"):
        return False
    if array(market.get("outcomes")) != ["Yes", "No"] or len(array(market.get("clobTokenIds"))) != 2:
        return False
    try:
        if sorted(map(float, array(market.get("outcomePrices")))) != [0.0, 1.0]:
            return False
    except (TypeError, ValueError):
        return False
    opened, closed = market.get("startDate") or market.get("createdAt"), market.get("closedTime")
    if not (opened and closed and market.get("conditionId")):
        return False
    opened, closed = timestamp(opened), timestamp(closed)
    return start <= closed < CUTOFF and closed - opened >= min_days * 86400


def discover(client, root, count, start, min_volume, min_days, tag_ids):
    """Step 1: page Gamma until `count` usable candidates are saved (resumable)."""
    path, state_path = root / "raw" / "candidates.jsonl.gz", root / "raw" / "discovery_state.json"
    found = read_jsonl(path)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"cursor": None, "done": False}
    seen = {m["conditionId"] for m in found}
    params = {"closed": True, "limit": 100,
              "end_date_min": iso(start), "end_date_max": iso(CUTOFF), "volume_num_min": min_volume,
              "tag_id": tag_ids or None}
    pages_read = 0
    while len(found) < count and not state["done"]:
        page = client.get(GAMMA, "/markets/keyset", **params, after_cursor=state["cursor"])
        batch = []
        for m in page.get("markets", []):
            if m.get("conditionId") in seen or not usable(m, start, min_days):
                continue
            seen.add(m["conditionId"])
            events = m.get("events") or [{"id": m["id"]}]
            batch.append({k: m.get(k) for k in ("id", "conditionId", "question", "outcomes", "outcomePrices",
                                                  "clobTokenIds", "closedTime", "startDate", "createdAt",
                                                  "endDate", "volumeNum")}
                         | {"event": {k: events[0].get(k) for k in ("id", "title", "slug")}})
        append_jsonl(path, batch)
        found.extend(batch)
        state = {"cursor": page.get("next_cursor"), "done": not page.get("next_cursor")}
        state_path.write_text(json.dumps(state))
        pages_read += 1
        if pages_read % 20 == 0:
            print(f"  discovery: {len(found)} candidates after {pages_read} pages")
    print(f"Discovery: {len(found)} candidate markets" + (" (Gamma has no more)" if state["done"] else ""))
    return found[:count]


def verify(client, root, candidates, start):
    """Step 2: confirm each outcome and when it became known; keep only pre-cutoff labels."""
    path = root / "raw" / "labels.jsonl.gz"
    done = {r["conditionId"]: r for r in read_jsonl(path)}
    todo = [m for m in candidates if m["conditionId"] not in done]
    for i in range(0, len(todo), 20):
        batch = todo[i:i + 20]
        resp = client.get(DATA, "/v2/resolutions", condition=",".join(m["conditionId"] for m in batch))
        got = {r.get("condition_id"): r for r in resp.get("data", [])}
        rows = []
        for m in batch:
            label = verified_resolution(m, got.get(m["conditionId"], {}), start, CUTOFF)
            rows.append({"conditionId": m["conditionId"], "label": label})
        append_jsonl(path, rows)
        done.update({r["conditionId"]: r for r in rows})
        if (i // 20) % 25 == 0:
            print(f"  verified {min(i + 20, len(todo))}/{len(todo)}")
    keep = [m | {"label": done[m["conditionId"]]["label"]} for m in candidates
            if done[m["conditionId"]]["label"] and done[m["conditionId"]]["label"]["label_available_at"] < CUTOFF]
    print(f"Verified: {len(keep)} of {len(candidates)} have a clean outcome known before the cutoff")
    return keep


def collect_one(root, m, max_pages):
    """Step 3: every fill for one market. Returns a status row (also saved for resuming)."""
    folder = root / "markets" / str(m["id"])
    status_path = folder / "status.json"
    if status_path.exists():
        return json.loads(status_path.read_text())
    try:
        rows, _, exhausted = pages(Client(), "/v2/trades",
                                   {"condition": m["conditionId"], "taker_only": False, "limit": 1000}, max_pages)
    except ApiError as exc:
        return {"id": m["id"], "ok": False, "reason": str(exc)[:200]}  # not saved: retried next run
    if not exhausted:
        status = {"id": m["id"], "ok": False, "reason": f"more than {max_pages * 1000} fills; skipped"}
    else:
        legs = [r for r in normalize_trades(rows) if r["timestamp"] < m["label"]["label_available_at"]]
        table(folder / "wallet_trade_legs.csv.gz", legs, LEG_FIELDS)
        status = {"id": m["id"], "ok": True, "fills": len(legs)}
    folder.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status))
    return status


def write_index(root, markets, statuses):
    rows = []
    for m in markets:
        s = statuses.get(str(m["id"]))
        if not s or not s.get("ok"):
            continue
        label = m["label"]
        rows.append({
            "market_id": m["id"], "condition_id": m["conditionId"], "event_id": m["event"]["id"],
            "economic_cluster_id": economic_cluster(m, m["event"]) if m.get("closedTime") else f"gamma-event:{m['event']['id']}",
            "question": m.get("question", ""), "subfield": subfield(m.get("question", "")),
            "yes_outcome": label["yes_outcome"], "label_available_at": label["label_available_at"],
            "label_available_at_utc": label["label_available_at_utc"], "fills": s["fills"],
            "folder": f"markets/{m['id']}",
        })
    rows.sort(key=lambda r: (r["label_available_at"], r["market_id"]))
    with (root / "markets.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MARKET_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=10000, help="markets to discover (some drop out later)")
    ap.add_argument("--start", default="2023-01-01", help="earliest close date to include")
    ap.add_argument("--min-volume", type=float, default=1000, help="skip markets that barely traded (USDC)")
    ap.add_argument("--min-days", type=int, default=3, help="minimum days the market was open")
    ap.add_argument("--tag-id", type=int, nargs="*", help="optional Gamma tag ids, e.g. a Finance tag")
    ap.add_argument("--max-pages", type=int, default=30, help="1,000 fills per page; bigger markets are skipped")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    start = timestamp(args.start)
    root = args.out
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps({
        "cutoff": iso(CUTOFF), "start": args.start, "count": args.count, "min_volume": args.min_volume,
        "min_days": args.min_days, "tag_id": args.tag_id, "max_pages": args.max_pages,
    }, indent=2))
    client = Client()

    candidates = discover(client, root, args.count, start, args.min_volume, args.min_days, args.tag_id)
    markets = verify(client, root, candidates, start)

    statuses, ok, skipped, failed = {}, 0, 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(collect_one, root, m, args.max_pages) for m in markets]
        for i, fut in enumerate(as_completed(futures), 1):
            s = fut.result()
            statuses[str(s["id"])] = s
            ok += s.get("ok", False)
            skipped += (not s.get("ok")) and "skipped" in s.get("reason", "")
            failed += (not s.get("ok")) and "skipped" not in s.get("reason", "")
            if i % 100 == 0 or i == len(markets):
                print(f"  trades: {i}/{len(markets)} markets ({ok} ok, {skipped} too big, {failed} failed)")

    rows = write_index(root, markets, statuses)
    print(f"\nDone: {len(rows)} markets ready in {root / 'markets.csv'}"
          f" ({skipped} too big, {failed} failed; rerun to retry failures).")
    print(f"Next: python -m polyresearch.backtest.tiers --history {root.as_posix()} datasets/finance/resolved-100-2025/v1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
