
"""SHARPSIDE research API. Category-aware historical wallet classification.

Requires: fastapi, uvicorn, supabase, python-dotenv.
Benchmark computation scans eligible category peers; cache/precompute for production.
"""
import logging
from math import isfinite
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import create_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
logger = logging.getLogger(__name__)
app = FastAPI(title="HackTheBruh Markets API")
# MAX_FINANCE_WALLETS = 100


def _create_supabase_client():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise HTTPException(503, "Supabase is not configured")
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/rest/v1"):
        url = urlunsplit(parsed._replace(path=path[:-len("/rest/v1")]))
    return create_client(url, key)


def _fetch_all(query, page_size: int = 1000):
    rows, offset = [], 0
    while True:
        batch = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += len(batch)


def _cutoff(value: int | None) -> int:
    return value if value is not None else int(datetime.now(timezone.utc).timestamp())


def _cluster_key(row: dict) -> str:
    # Prevent a missing cluster ID from collapsing unrelated markets.
    return str(row.get("economic_cluster_id") or f"market:{row['market_id']}")


def _get_returns(db, cutoff: int, category: str | None = None,
                 wallet: str | None = None,
                 market_ids: list[str] | None = None) -> list[dict]:
    if market_ids is not None and not market_ids:
        return []

    def build_query():
        q = (db.table("research_returns")
             .select("wallet,market_id,economic_cluster_id,category,available_at,"
                     "reported_realized_pnl_usdc,estimated_entry_basis_usdc,usable")
             .eq("usable", True).lte("available_at", cutoff)
             .order("wallet").order("market_id"))
        if wallet is not None:
            q = q.eq("wallet", wallet)
        if category is not None:
            q = q.eq("category", category)
        return q

    if market_ids is None:
        return _fetch_all(build_query())

    rows = []
    for offset in range(0, len(market_ids), 100):
        rows.extend(_fetch_all(build_query().in_("market_id", market_ids[offset:offset + 100])))
    return rows


def _eligible_returns(rows: list[dict], excluded_market: str | None,
                      excluded_cluster: str | None) -> list[dict]:
    print("rows len", len(rows))
    eligible = []
    for r in rows:
        if excluded_market is not None and r["market_id"] == excluded_market:
            continue
        if excluded_cluster is not None and r.get("economic_cluster_id") == excluded_cluster:
            continue
        if r.get("available_at") is None or r.get("reported_realized_pnl_usdc") is None:
            continue
        basis = r.get("estimated_entry_basis_usdc")
        if basis is None or float(basis) <= 0:
            continue
        eligible.append(r)
    return eligible


def _edge_proxy(db, wallet: str, market_ids: list[str], cutoff: int,
                dataset_keys: list[str] | None = None) -> tuple[float | None, int]:
    """Share-weighted (settlement - entry) on BUY-only markets.

    Only valid if the trade dataset is complete and buys were held to settlement.
    Any market with a SELL is excluded. This is NOT an exact active-trader edge.
    """
    if not market_ids:
        return None, 0
    markets, trades = [], []
    keys = dataset_keys or [None]
    for dataset_key in keys:
        for i in range(0, len(market_ids), 100):
            ids = market_ids[i:i + 100]
            market_query = (db.table("research_markets")
                            .select("dataset_key,market_id,yes_outcome,label_available_at")
                            .in_("market_id", ids)
                            .lte("label_available_at", cutoff)
                            .order("dataset_key").order("market_id"))
            trade_query = (db.table("research_trades")
                           .select("dataset_key,market_id,source_row,side,outcome,size_shares,price,observed_at")
                           .eq("wallet", wallet).in_("market_id", ids)
                           .lte("observed_at", cutoff)
                           .order("dataset_key").order("market_id").order("source_row"))
            if dataset_key is not None:
                market_query = market_query.eq("dataset_key", dataset_key)
                trade_query = trade_query.eq("dataset_key", dataset_key)
            markets.extend(_fetch_all(market_query))
            trades.extend(_fetch_all(trade_query))
    labels = defaultdict(list)
    for m in markets:
        if m["yes_outcome"] in (0, 1):
            labels[(m["dataset_key"], m["market_id"])].append(m["yes_outcome"])
    grouped = defaultdict(list)
    for trade in trades:
        grouped[(trade["dataset_key"], trade["market_id"])].append(trade)

    edge_sum, shares_sum, eligible_markets = 0.0, 0.0, 0
    for key, legs in grouped.items():
        if len(labels.get(key, [])) != 1 or not legs:
            continue
        if any(str(t["side"]).upper() != "BUY" for t in legs):
            continue
        local_edge, local_shares = 0.0, 0.0
        for t in legs:
            outcome = str(t["outcome"]).upper()
            if outcome not in ("YES", "NO") or t["price"] is None or t["size_shares"] is None:
                break
            price, shares = float(t["price"]), float(t["size_shares"])
            if not (0 <= price <= 1 and shares > 0):
                break
            won = (labels[key][0] == 1) == (outcome == "YES")
            local_edge += shares * (float(won) - price)
            local_shares += shares
        else:  # All trade legs were valid.
            if local_shares > 0:
                edge_sum += local_edge
                shares_sum += local_shares
                eligible_markets += 1
    return (edge_sum / shares_sum if shares_sum else None), eligible_markets


def _summarize_wallet(db, wallet: str, rows: list[dict], cutoff: int,
                      calculate_edge: bool = True,
                      dataset_keys: list[str] | None = None) -> dict | None:
    if not rows:
        print("no rows")
        return None
    pnl = sum(float(r["reported_realized_pnl_usdc"]) for r in rows)
    basis = sum(float(r["estimated_entry_basis_usdc"]) for r in rows)
    independent = len({_cluster_key(r) for r in rows})
    edge, edge_count = (None, 0)
    if calculate_edge:
        edge, edge_count = _edge_proxy(
            db, wallet, sorted({r["market_id"] for r in rows}), cutoff, dataset_keys
        )

    print(f"wallet:{wallet}")
    print(f"wallet:{wallet}")

    return {
        "wallet": wallet,
        "realized_pnl_usdc": pnl,
        "estimated_roi": pnl / basis,
        "profitable_market_rate": sum(float(r["reported_realized_pnl_usdc"]) > 0 for r in rows) / len(rows),
        "completed_markets": len(rows),
        "independent_resolved_markets": independent,
        "confidence_weight": independent / (independent + 20),
        "market_relative_edge_proxy": edge,
        "edge_eligible_markets": edge_count,
    }


def _target_exclusions(db, market_id: str | None) -> tuple[str | None, str | None]:
    if not market_id:
        return None, None
    records = (db.table("research_markets")
               .select("economic_cluster_id")
               .eq("market_id", market_id).limit(2).execute().data or [])
    if not records:
        raise HTTPException(404, "Target market not found")
    clusters = {r.get("economic_cluster_id") for r in records if r.get("economic_cluster_id")}
    if len(clusters) > 1:
        raise HTTPException(409, "Target market has ambiguous economic clusters across datasets")
    return market_id, next(iter(clusters), None)


@app.get("/markets")
def get_markets():
    try:
        return _fetch_all(_create_supabase_client().table("research_markets")
                          .select("*").order("dataset_key").order("market_id"))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch markets")
        raise HTTPException(502, "Failed to fetch markets") from exc


def _get_finance_markets() -> list[dict]:
    return [
        market for market in get_markets()
        if "finance" in str(market.get("dataset_key", "")).lower()
    ]


@app.get("/wallets/finance")
def get_all_wallets() -> list[dict[str, Any]]:
    """Return wallets and their market IDs from finance datasets."""
    try:
        finance_markets = _get_finance_markets()
        markets_by_dataset: dict[str, set[str]] = defaultdict(set)
        for market in finance_markets:
            dataset_key = market.get("dataset_key")
            market_id = market.get("market_id")
            if dataset_key and market_id:
                markets_by_dataset[dataset_key].add(market_id)

        db = _create_supabase_client()
        wallets_by_market: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for dataset_key in sorted(markets_by_dataset):
            finance_market_ids = sorted(markets_by_dataset[dataset_key])
            for offset in range(0, len(finance_market_ids), 100):
                trades = _fetch_all(
                    db.table("research_trades")
                    .select("wallet,market_id,source_row")
                    .eq("dataset_key", dataset_key)
                    .in_("market_id", finance_market_ids[offset:offset + 100])
                    .not_.is_("wallet", "null")
                    .order("market_id").order("source_row")
                )
                for trade in trades:
                    wallet, market_id = trade.get("wallet"), trade.get("market_id")
                    if wallet and market_id in markets_by_dataset[dataset_key]:
                        wallets_by_market[wallet].add((dataset_key, market_id))

        wallets = [
            {
                "wallet_id": wallet,
                "markets": [
                    {"dataset_key": dataset_key, "market_id": market_id}
                    for dataset_key, market_id in sorted(markets)
                ],
            }
            for wallet, markets in sorted(wallets_by_market.items())
        ]
        return wallets
    # [:MAX_FINANCE_WALLETS]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch finance wallets")
        raise HTTPException(502, "Failed to fetch finance wallets") from exc


def _load_finance_trade_evidence(db, wallet_markets: list[dict], cutoff: int):
    """Load resolved finance markets and their wallet trade legs up to cutoff."""
    market_ids_by_dataset: dict[str, set[str]] = defaultdict(set)
    for entry in wallet_markets:
        for market in entry["markets"]:
            market_ids_by_dataset[market["dataset_key"]].add(market["market_id"])

    markets, trades = [], []
    for dataset_key, market_ids in sorted(market_ids_by_dataset.items()):
        ids = sorted(market_ids)
        for offset in range(0, len(ids), 100):
            batch_ids = ids[offset:offset + 100]
            markets.extend(_fetch_all(
                db.table("research_markets")
                .select("dataset_key,market_id,economic_cluster_id,category,yes_outcome,label_available_at")
                .eq("dataset_key", dataset_key)
                .in_("market_id", batch_ids)
                .lte("label_available_at", cutoff)
                .order("market_id")
            ))
            trades.extend(_fetch_all(
                db.table("research_trades")
                .select("wallet,dataset_key,market_id,side,outcome,size_shares,price,observed_at")
                .eq("dataset_key", dataset_key)
                .in_("market_id", batch_ids)
                .lte("observed_at", cutoff)
                .order("market_id").order("observed_at")
            ))
    return markets, trades


def _trade_return_rows(
    wallet_markets: list[dict],
    market_rows: list[dict],
    trade_rows: list[dict],
    cutoff: int,
) -> dict[str, list[dict]]:
    """Estimate resolved-market PnL from buys, sells, and settlement payouts."""
    wallets_by_market: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in wallet_markets:
        for market in entry["markets"]:
            wallets_by_market[
                (market["dataset_key"], market["market_id"])
            ].add(entry["wallet_id"])

    resolved_markets = {}
    for market in market_rows:
        outcome = market.get("yes_outcome")
        available_at = market.get("label_available_at")
        key = (market["dataset_key"], market["market_id"])
        if (
            outcome in (0, 1)
            and available_at is not None
            and int(available_at) <= cutoff
        ):
            resolved_markets[key] = market

    trades_by_wallet_market: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for trade in trade_rows:
        key = (trade["dataset_key"], trade["market_id"])
        wallet = trade["wallet"]
        if key in resolved_markets and wallet in wallets_by_market.get(key, set()):
            trades_by_wallet_market[
                (wallet, trade["dataset_key"], trade["market_id"])
            ].append(trade)

    result: dict[str, list[dict]] = defaultdict(list)
    for (wallet, dataset_key, market_id), legs in trades_by_wallet_market.items():
        cash_flow = 0.0
        buy_cost = 0.0
        inventory = {"YES": 0.0, "NO": 0.0}
        valid = True
        for leg in legs:
            side = str(leg["side"]).upper()
            outcome = str(leg["outcome"]).upper()
            shares = float(leg["size_shares"])
            price = float(leg["price"])
            if (
                side not in ("BUY", "SELL")
                or outcome not in inventory
                or not isfinite(shares)
                or not isfinite(price)
                or shares < 0
                or not 0 <= price <= 1
            ):
                valid = False
                break
            signed_shares = shares if side == "BUY" else -shares
            signed_cash = shares * price * (-1 if side == "BUY" else 1)
            inventory[outcome] += signed_shares
            cash_flow += signed_cash
            if side == "BUY":
                buy_cost += shares * price

        # A net short position can indicate missing pre-window inventory, so
        # do not treat it as a complete return observation.
        if not valid or buy_cost <= 0 or min(inventory.values()) < -1e-8:
            continue

        market = resolved_markets[(dataset_key, market_id)]
        yes_payout = inventory["YES"] if market["yes_outcome"] == 1 else 0.0
        no_payout = inventory["NO"] if market["yes_outcome"] == 0 else 0.0
        pnl = cash_flow + yes_payout + no_payout
        result[wallet].append({
            "wallet": wallet,
            "dataset_key": dataset_key,
            "market_id": market_id,
            "economic_cluster_id": market.get("economic_cluster_id"),
            "category": market.get("category"),
            "reported_realized_pnl_usdc": pnl,
            "estimated_entry_basis_usdc": buy_cost,
        })
    return result


def _trade_edge_by_wallet(
    wallet_markets: list[dict],
    market_rows: list[dict],
    trade_rows: list[dict],
    cutoff: int,
) -> dict[str, tuple[float | None, int]]:
    """Calculate the existing BUY-only edge proxy from already-loaded batch rows."""
    wallets_by_market: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in wallet_markets:
        for market in entry["markets"]:
            wallets_by_market[(market["dataset_key"], market["market_id"])].add(
                entry["wallet_id"]
            )

    labels: dict[tuple[str, str], list[int]] = defaultdict(list)
    for market in market_rows:
        outcome = market.get("yes_outcome")
        available_at = market.get("label_available_at")
        if (
            outcome in (0, 1)
            and available_at is not None
            and int(available_at) <= cutoff
        ):
            labels[(market["dataset_key"], market["market_id"])].append(outcome)

    grouped_trades: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for trade in trade_rows:
        key = (trade["dataset_key"], trade["market_id"])
        wallet = trade["wallet"]
        if (
            key in labels
            and len(labels[key]) == 1
            and wallet in wallets_by_market.get(key, ())
        ):
            grouped_trades[(wallet, *key)].append(trade)

    edge_by_wallet: dict[str, list[float | int]] = defaultdict(
        lambda: [0.0, 0.0, 0]
    )
    for (wallet, dataset_key, market_id), legs in grouped_trades.items():
        if not legs or any(str(leg.get("side", "")).upper() != "BUY" for leg in legs):
            continue
        edge_sum, shares_sum = 0.0, 0.0
        yes_outcome = labels[(dataset_key, market_id)][0]
        for leg in legs:
            outcome = str(leg.get("outcome", "")).upper()
            shares_value, price_value = leg.get("size_shares"), leg.get("price")
            if outcome not in ("YES", "NO") or shares_value is None or price_value is None:
                break
            shares, price = float(shares_value), float(price_value)
            if (
                not isfinite(shares)
                or not isfinite(price)
                or shares <= 0
                or not 0 <= price <= 1
            ):
                break
            won = (yes_outcome == 1) == (outcome == "YES")
            edge_sum += shares * (float(won) - price)
            shares_sum += shares
        else:
            if shares_sum > 0:
                totals = edge_by_wallet[wallet]
                totals[0] += edge_sum
                totals[1] += shares_sum
                totals[2] += 1

    return {
        wallet: (
            totals[0] / totals[1] if totals[1] else None,
            int(totals[2]),
        )
        for wallet, totals in edge_by_wallet.items()
    }


def _summarize_trade_wallet(
    db,
    wallet: str,
    rows: list[dict],
    cutoff: int,
    calculate_edge: bool = True,
    dataset_keys: list[str] | None = None,
) -> dict | None:
    """Summarize estimated resolved-market performance derived from trades."""
    stats = _summarize_wallet(
        db, wallet, rows, cutoff, calculate_edge=calculate_edge,
        dataset_keys=dataset_keys
    )
    if stats is not None:
        stats["trade_derived_pnl_usdc"] = stats.pop("realized_pnl_usdc")
    return stats


def _median_excluding(values: list[float], excluded_index: int | None) -> float | None:
    """Return a median from sorted values, optionally omitting one indexed value."""
    count = len(values)
    if excluded_index is not None:
        count -= 1
    if count <= 0:
        return None

    def value_at(index: int) -> float:
        if excluded_index is not None and index >= excluded_index:
            index += 1
        return values[index]

    lower = (count - 1) // 2
    upper = count // 2
    return (value_at(lower) + value_at(upper)) / 2


@app.get("/markets/{market_id}/wallets")
def get_market_wallets(market_id: str, cutoff: int | None = Query(None, gt=0),
                       limit: int = Query(5, ge=1, le=100)):
    try:
        db = _create_supabase_client()
        q = (db.table("research_trades").select("wallet,observed_at,dataset_key,market_id,source_row")
             .eq("market_id", market_id).not_.is_("wallet", "null")
             .order("dataset_key").order("market_id").order("source_row"))
        if cutoff is not None:
            q = q.lte("observed_at", cutoff)
        seen, wallets = set(), []
        # Iterate pages rather than arbitrarily truncating at 1000 trade rows.
        offset, page_size = 0, 1000
        while len(wallets) < limit:
            batch = q.range(offset, offset + page_size - 1).execute().data or []
            for row in batch:
                w = row["wallet"]
                if w not in seen:
                    seen.add(w)
                    wallets.append(w)
                    if len(wallets) == limit:
                        break
            if len(batch) < page_size:
                break
            offset += len(batch)
        return {"market_id": market_id, "cutoff": cutoff, "wallet_ids": wallets, "count": len(wallets)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch market wallets")
        raise HTTPException(502, "Failed to fetch market wallets") from exc


@app.get("/wallets/{wallet_id}/stats")
def get_wallet_stats(wallet_id: str, category: str | None = None,
                     cutoff: int | None = Query(None, gt=0),
                     target_market_id: str | None = None):
    try:
        db = _create_supabase_client()
        t = _cutoff(cutoff)
        excluded_market, excluded_cluster = _target_exclusions(db, target_market_id)
        rows = _eligible_returns(_get_returns(db, t, category, wallet_id),
                                 excluded_market, excluded_cluster)
        stats = _summarize_wallet(db, wallet_id, rows, t)
        if stats is None:
            raise HTTPException(404, "No usable completed returns for this wallet in the selected category/cutoff")
        return {**stats, "category": category, "cutoff": t, "target_market_id": target_market_id,
                "edge_method": "share-weighted BUY-only settled trade proxy; requires complete trade history"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Wallet stats failed")
        raise HTTPException(502, "Failed to calculate wallet stats") from exc


class SkillClassificationRequest(BaseModel):
    category: str = Field(min_length=1)
    cutoff: int | None = Field(default=None, gt=0)
    target_market_id: str | None = None
    minimum_confidence: float = Field(default=0.60, ge=0, le=1)
    minimum_peer_markets: int = Field(default=5, ge=1)


@app.post("/wallets/{wallet_id}/classify")
def classify_wallet(wallet_id: str, payload: SkillClassificationRequest):
    """Benchmark against other wallets' historical results in the same category.

    Median of per-wallet PnL/ROI/profitable-market-rate/edge (not pooled trade rows).
    Includes all eligible peers, not only winners. Slow for large peer populations.
    """
    try:
        db = _create_supabase_client()
        t = _cutoff(payload.cutoff)
        excluded_market, excluded_cluster = _target_exclusions(db, payload.target_market_id)
        all_rows = _eligible_returns(_get_returns(db, t, payload.category),
                                     excluded_market, excluded_cluster)
        by_wallet = defaultdict(list)
        for r in all_rows:
            by_wallet[r["wallet"]].append(r)
        wallet_stats = _summarize_wallet(db, wallet_id, by_wallet.get(wallet_id, []), t)
        if wallet_stats is None:
            return {"wallet": wallet_id, "category": payload.category, "cutoff": t,
                    "classification": "unskilled", "reason": "insufficient_history",
                    "note": "Unskilled means not qualified, not proven lack of skill."}

        peer_stats = []
        for peer, rows in by_wallet.items():
            if peer == wallet_id:
                continue
            independent = len({_cluster_key(r) for r in rows})
            if independent < payload.minimum_peer_markets:
                continue
            s = _summarize_wallet(db, peer, rows, t)
            if s is not None:
                peer_stats.append(s)
        if not peer_stats:
            raise HTTPException(422, "No eligible historical peers in this category")

        metric_names = ("realized_pnl_usdc", "estimated_roi", "profitable_market_rate",
                        "market_relative_edge_proxy")
        benchmark = {}
        for name in metric_names:
            values = [p[name] for p in peer_stats if p[name] is not None]
            benchmark[name] = median(values) if values else None
        checks = {name: wallet_stats[name] is not None and benchmark[name] is not None
                  and wallet_stats[name] > benchmark[name] for name in metric_names}
        confidence_passed = wallet_stats["confidence_weight"] >= payload.minimum_confidence
        skilled = confidence_passed and all(checks.values())
        return {
            "wallet": wallet_id,
            "category": payload.category,
            "cutoff": t,
            "target_market_id": payload.target_market_id,
            "classification": "skilled" if skilled else "unskilled",
            "reason": "all_criteria_passed" if skilled else "criteria_not_met_or_insufficient_evidence",
            "wallet_stats": wallet_stats,
            "peer_benchmark_median": benchmark,
            "peer_wallet_count": len(peer_stats),
            "peer_wallets_with_edge": sum(p["market_relative_edge_proxy"] is not None for p in peer_stats),
            "metrics_passed": checks,
            "confidence_passed": confidence_passed,
            "minimum_confidence": payload.minimum_confidence,
            "notes": [
                "Benchmarks are medians of historical eligible category peers, excluding the target wallet.",
                "PnL is not capital-normalized; ROI is an estimated entry-basis proxy.",
                "Profitable-market rate is not individual-trade win rate.",
                "Edge is a BUY-only held-to-settlement proxy, not exact for active trading.",
                "Unskilled means did not qualify, not proof of poor skill."
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Category classification failed")
        raise HTTPException(502, "Failed to classify wallet") from exc


@app.get("/wallets/finance/results")
def get_wallets_result() -> dict[str, str]:
    """Classify finance wallets using trade-derived resolved-market performance."""
    try:
        wallet_markets = get_all_wallets()
        wallets = sorted({entry["wallet_id"] for entry in wallet_markets})
        if not wallets:
            return {}

        db = _create_supabase_client()
        cutoff = _cutoff(None)
        market_rows, trade_rows = _load_finance_trade_evidence(
            db, wallet_markets, cutoff
        )
        performance_rows_by_wallet = _trade_return_rows(
            wallet_markets, market_rows, trade_rows, cutoff
        )
        edge_by_wallet = _trade_edge_by_wallet(
            wallet_markets, market_rows, trade_rows, cutoff
        )
        markets_by_wallet = {
            entry["wallet_id"]: {
                (market["dataset_key"], market["market_id"])
                for market in entry["markets"]
            }
            for entry in wallet_markets
        }

        stats_by_wallet = {}
        for wallet in wallets:
            wallet_dataset_keys = sorted({
                dataset_key
                for dataset_key, _ in markets_by_wallet.get(wallet, set())
            })
            stats = _summarize_trade_wallet(
                db,
                wallet,
                performance_rows_by_wallet.get(wallet, []),
                cutoff,
                calculate_edge=False,
                dataset_keys=wallet_dataset_keys,
            )
            if stats is not None:
                edge, edge_count = edge_by_wallet.get(wallet, (None, 0))
                stats["market_relative_edge_proxy"] = edge
                stats["edge_eligible_markets"] = edge_count
                stats_by_wallet[wallet] = stats

        eligible_peers = {
            wallet: stats
            for wallet, stats in stats_by_wallet.items()
            if stats["independent_resolved_markets"] >= 5
        }
        #condition
        metric_names = (
            "trade_derived_pnl_usdc",
            "estimated_roi",
            "profitable_market_rate",
            "market_relative_edge_proxy",
        )
        peer_values_by_metric: dict[str, list[float]] = {}
        peer_index_by_metric: dict[str, dict[str, int]] = {}
        for name in metric_names:
            ordered = sorted(
                (float(stats[name]), peer_wallet)
                for peer_wallet, stats in eligible_peers.items()
                if stats[name] is not None
            )
            peer_values_by_metric[name] = [value for value, _ in ordered]
            peer_index_by_metric[name] = {
                peer_wallet: index
                for index, (_, peer_wallet) in enumerate(ordered)
            }

        results = {}
        for wallet in wallets:
            stats = stats_by_wallet.get(wallet)
            # condition If the wallet has no stats, classify as unskilled (insufficient history).
            if stats is None: #unskilled
                results[wallet] = "unskilled"
                continue

            checks = {}
            for name in metric_names:
                benchmark = _median_excluding(
                    peer_values_by_metric[name],
                    peer_index_by_metric[name].get(wallet),
                )
                value = stats[name]
                checks[name] = (
                    value is not None and benchmark is not None and value > benchmark
                )
            #condition : 0.60 -> 30  = independent_resolved_markets / (independent_resolved_markets + 20)
            confident = stats["confidence_weight"] >= 0.40
            results[wallet] = (
                "skilled" if confident and all(checks.values()) else "unskilled"
            )
        return results
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Finance wallet classification failed")
        raise HTTPException(502, "Failed to classify finance wallets") from exc


@app.get("/wallets/{wallet_id}/research-trades")
def get_wallet_research_trades(
    wallet_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return a page of raw research_trades rows for a wallet."""
    try:
        db = _create_supabase_client()
        rows = (
            db.table("research_trades")
            .select("*")
            .eq("wallet", wallet_id)
            .order("dataset_key")
            .order("market_id")
            .order("source_row")
            .range(offset, offset + limit - 1)
            .execute()
            .data
            or []
        )
        return {
            "wallet_id": wallet_id,
            "count": len(rows),
            "limit": limit,
            "offset": offset,
            "rows": rows,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch research trades for %s", wallet_id)
        raise HTTPException(502, "Failed to fetch wallet research trades") from exc


@app.get("/wallets/{wallet_id}/research-returns")
def get_wallet_research_returns(
    wallet_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return a page of raw research_returns rows for a wallet."""
    try:
        db = _create_supabase_client()
        rows = (
            db.table("research_returns")
            .select("*")
            .eq("wallet", wallet_id)
            .order("market_id")
            .range(offset, offset + limit - 1)
            .execute()
            .data
            or []
        )
        return {
            "wallet_id": wallet_id,
            "count": len(rows),
            "limit": limit,
            "offset": offset,
            "rows": rows,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch research returns for %s", wallet_id)
        raise HTTPException(502, "Failed to fetch wallet research returns") from exc


@app.get("/wallets/{wallet_id}/finance-check")
def check_finance_wallet(wallet_id: str, cutoff: int | None = Query(None, gt=0)) -> dict[str, Any]:
    """Explain the trade-derived resolved-market performance available for a wallet."""
    try:
        effective_cutoff = _cutoff(cutoff)
        db = _create_supabase_client()
        wallet_batch = get_all_wallets()
        wallet_entry = next(
            (entry for entry in wallet_batch if entry["wallet_id"] == wallet_id),
            None,
        )
        selected_wallets = [wallet_entry] if wallet_entry else []
        market_rows, trade_rows = _load_finance_trade_evidence(
            db, selected_wallets, effective_cutoff
        )
        performance_rows = _trade_return_rows(
            selected_wallets, market_rows, trade_rows, effective_cutoff
        ).get(wallet_id, [])
        finance_pairs = sorted({
            (market["dataset_key"], market["market_id"])
            for market in wallet_entry["markets"]
        }) if wallet_entry else []
        stats = _summarize_trade_wallet(
            db,
            wallet_id,
            performance_rows,
            effective_cutoff,
            dataset_keys=sorted({dataset_key for dataset_key, _ in finance_pairs}),
        )
        if not finance_pairs:
            reason = "wallet_has_no_finance_trades"
        elif not performance_rows:
            reason = "no_resolved_markets_with_usable_trade_history"
        else:
            reason = "trade_derived_stats_available"
        return {
            "wallet_id": wallet_id,
            "cutoff": effective_cutoff,
            "included_in_current_finance_wallet_batch": wallet_entry is not None,
            "finance_trade_market_count": len(finance_pairs),
            "finance_trade_markets": [
                {"dataset_key": dataset_key, "market_id": market_id}
                for dataset_key, market_id in finance_pairs
            ],
            "resolved_trade_market_count": len(performance_rows),
            "would_stats_be_none": stats is None,
            "reason": reason,
            "trade_derived_returns": performance_rows,
            "performance_metrics": stats,
            "note": (
                "PnL is estimated as trade cash flows plus settlement payouts for "
                "resolved finance markets. Markets with net short inventories or no "
                "buy-cost basis are excluded. This does not account for fees, "
                "transfers, or inventory acquired outside the recorded trades."
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Finance wallet trade analysis failed for %s", wallet_id)
        raise HTTPException(502, "Failed to analyze finance wallet trades") from exc
