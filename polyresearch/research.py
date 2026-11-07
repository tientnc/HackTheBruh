"""Collection and transparent wallet heuristics, with explicit coverage metadata."""

import math
from datetime import datetime, timezone

from .client import DATA, GAMMA, ApiError, pages


def timestamp(value):
    """Dates and zone-less ISO timestamps are interpreted as UTC."""
    if isinstance(value, (int, float)):
        return int(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def now():
    return datetime.now(timezone.utc).isoformat()


def array(value):
    import json
    return json.loads(value) if isinstance(value, str) else (value or [])


def discover(client, start=None, end=None, max_events=100, status="all"):
    tag = client.get(GAMMA, "/tags/slug/finance")
    events, markets, offset = [], {}, 0
    exhausted = False
    while len(events) < max_events:
        limit = min(100, max_events - len(events))
        params = dict(tag_id=tag["id"], limit=limit, offset=offset,
                      order="id", ascending=True)
        if status != "all":
            params["closed"] = status == "closed"
        batch = client.get(GAMMA, "/events", **params)
        if not isinstance(batch, list):
            raise ApiError("Unexpected Gamma events schema")
        events.extend(batch)
        for event in batch:
            for market in event.get("markets", []):
                if status != "all" and bool(market.get("closed")) != (status == "closed"):
                    continue
                opened = market.get("startDate") or market.get("createdAt")
                ended = market.get("endDate")
                if end is not None and opened and timestamp(opened) >= end:
                    continue
                if start is not None and ended and timestamp(ended) < start:
                    continue
                tokens = array(market.get("clobTokenIds"))
                outcomes = array(market.get("outcomes"))
                prices = array(market.get("outcomePrices"))
                if not market.get("conditionId"):
                    continue
                markets[market["conditionId"]] = {
                    "condition_id": market["conditionId"],
                    "market_id": market["id"], "event_id": event["id"],
                    "event_title": event.get("title"), "question": market.get("question"),
                    "slug": market.get("slug"), "start_date": opened, "end_date": ended,
                    "closed_now": market.get("closed"),
                    "version": market.get("version"),
                    "outcomes": [{"label": label,
                                  "token_id": tokens[i] if i < len(tokens) else None,
                                  "price_now": prices[i] if i < len(prices) else None}
                                 for i, label in enumerate(outcomes)],
                }
        offset += len(batch)
        if len(batch) < limit:
            exhausted = True
            break
    return {"collected_at": now(), "tag": tag, "start": start, "end": end,
            "status": status, "events_scanned": len(events),
            "discovery_exhausted": exhausted, "markets": list(markets.values()),
            "raw_events": events,
            "warning": "Current metadata and tags are retrospective. Discovery is bounded; "
                       "date overlap is a candidate filter, not proof of historical trading."}


def collect_trades(client, condition, start, end, max_pages=20):
    # Market-shaped v2 requests IGNORE start/end and return a fixed three-year window.
    # Filter locally after walking the feed; never claim that a date parameter did it.
    rows, raw, complete = pages(client, "/v2/trades", {
        "condition": condition, "taker_only": True, "limit": 1000,
    }, max_pages)
    selected = [r for r in rows if start <= int(r["timestamp"]) < end]
    # Retention bounds are an independent limitation even when pagination exhausted.
    retention_floor = int(datetime.now(timezone.utc).timestamp()) - 3 * 366 * 86400
    return {"collected_at": now(), "condition_id": condition, "start": start, "end": end,
            "pagination_exhausted": complete,
            "window_within_documented_retention": start >= retention_floor,
            "rows_scanned": len(rows), "pages_fetched": len(raw),
            "earliest_scanned": min((int(r["timestamp"]) for r in rows), default=None),
            "latest_scanned": max((int(r["timestamp"]) for r in rows), default=None),
            "trades": selected, "raw_pages": raw,
            "warning": "Taker-side fills only; excludes passive maker signals. "
                       "Exhausting the feed is not a guarantee of source completeness."}


def collect_prices(client, token, start, end, bucket_seconds=10800, max_pages=20):
    points, windows = [], []
    cursor_start = start
    complete = True
    while cursor_start < end:
        stop = min(end, cursor_start + 15 * 86400)
        rows, raw, done = pages(client, "/v2/prices-history", {
            "token_id": token, "start": cursor_start, "end": stop,
            "bucket_seconds": bucket_seconds, "limit": 10000,
        }, max_pages)
        points.extend(r for r in rows if start <= int(r["timestamp"]) < end)
        windows.append({"start": cursor_start, "end": stop,
                        "pagination_exhausted": done, "raw_pages": raw})
        complete = complete and done
        cursor_start = stop
    return {"collected_at": now(), "token_id": token, "start": start, "end": end,
            "bucket_seconds_requested": bucket_seconds, "pagination_exhausted": complete,
            "points": points, "windows": windows,
            "warning": "Empty series means unavailable, not zero. For features, an aggregate "
                       "is available only at timestamp + resolution_seconds; settlement "
                       "points are labels, not pre-resolution features."}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def classify(snapshot, min_trades=100, min_profit=0):
    count, profit = snapshot.get("trade_count"), snapshot.get("realized_trading_profit")
    if not snapshot.get("history_exhausted") or not finite(count) or not finite(profit):
        return "unknown"
    return "skilled" if count >= min_trades and profit > min_profit else "unskilled"


def wallet_snapshot(client, wallet, as_of, max_pages=20, min_trades=100, min_profit=0):
    # as_of is EXCLUSIVE throughout: no trade or P&L observation at/after it may enter.
    trades, trade_pages, complete = pages(client, "/v2/trades", {
        "user": wallet, "taker_only": False, "start": 1, "end": as_of - 1, "limit": 1000,
    }, max_pages)
    trades = [t for t in trades if int(t["timestamp"]) < as_of]
    pnl = client.get(DATA, "/v2/user-pnl", user=wallet, interval="max", fidelity="1d")
    data = pnl.get("data") or {}
    points = [p for p in data.get("points", []) if int(p["timestamp"]) < as_of]
    point = max(points, key=lambda p: int(p["timestamp"]), default=None)
    # Never substitute total P&L, rewards, current profit or a missing value as zero.
    profit = None
    if point and finite(point.get("realized_market_pnl")) and finite(point.get("realized_combo_pnl")):
        profit = point["realized_market_pnl"] + point["realized_combo_pnl"]
    snapshot = {"wallet": wallet.lower(), "as_of": as_of, "collected_at": now(),
                "trade_count": len(trades),
                "distinct_markets": len({t["condition_id"] for t in trades}),
                "history_exhausted": complete,
                "realized_trading_profit": profit,
                "pnl_observed_at": point["timestamp"] if point else None,
                "pnl_source_fidelity": data.get("source_fidelity"),
                "thresholds": {"min_trades": min_trades, "profit_strictly_above": min_profit},
                "raw_trade_pages": trade_pages, "raw_pnl": pnl,
                "scope": "All-market lifetime fills and realized trading profit before cutoff; "
                         "not finance-specific skill. Trade count includes maker and taker rows."}
    snapshot["label"] = classify(snapshot, min_trades, min_profit)
    return snapshot


def cohorts(trade_data, snapshots, wallet_cap=1000, min_trades=100, min_profit=0):
    if not finite(wallet_cap) or wallet_cap <= 0:
        raise ValueError("wallet_cap must be a finite positive number")
    start, end = trade_data["start"], trade_data["end"]
    # Require labels frozen before the flow window, not after seeing that window's trades.
    lookup = {}
    rejected = 0
    for snapshot in snapshots:
        if snapshot["as_of"] > start:
            rejected += 1
            continue
        wallet = snapshot["wallet"].lower()
        if wallet not in lookup or snapshot["as_of"] > lookup[wallet]["as_of"]:
            lookup[wallet] = snapshot
    net, skipped = {}, 0
    condition = trade_data["condition_id"]
    for row in trade_data["trades"]:
        if row.get("condition_id") != condition or not start <= int(row["timestamp"]) < end:
            skipped += 1
            continue
        label, side = str(row.get("outcome", "")).lower(), row.get("side")
        size, price = row.get("size"), row.get("price")
        wallet = row.get("proxy_wallet")
        if (label not in ("yes", "no") or side not in ("BUY", "SELL") or not wallet
                or not finite(size) or size < 0 or not finite(price) or not 0 <= price <= 1):
            skipped += 1
            continue
        sign = (1 if label == "yes" else -1) * (1 if side == "BUY" else -1)
        wallet = wallet.lower()
        net[wallet] = net.get(wallet, 0) + sign * size * price
    groups = {f"{skill}_{direction}": {"wallets": 0, "capped_signed_flow_usdc": 0.0}
              for skill in ("skilled", "unskilled", "unknown")
              for direction in ("agree", "disagree", "neutral")}
    for wallet, flow in net.items():
        skill = classify(lookup.get(wallet, {}), min_trades, min_profit)
        direction = "neutral" if abs(flow) < 1e-9 else "agree" if flow > 0 else "disagree"
        group = groups[f"{skill}_{direction}"]
        group["wallets"] += 1
        group["capped_signed_flow_usdc"] += max(-wallet_cap, min(wallet_cap, flow))
    return {"condition_id": condition, "start": start, "end": end,
            "groups": groups, "wallets_observed": len(net), "rows_skipped": skipped,
            "future_snapshots_rejected": rejected, "wallet_flow_cap_usdc": wallet_cap,
            "thresholds": {"min_trades": min_trades, "profit_strictly_above": min_profit},
            "trade_pagination_exhausted": trade_data["pagination_exhausted"],
            "meaning": "Agree = positive net YES-direction cash flow; disagree = negative. "
                       "These are behavior features, not nomination odds or calibrated forecasts. "
                       "Unskilled means baseline not met, not demonstrated lack of skill."}
