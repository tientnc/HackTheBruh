
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from supabase import create_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)
app = FastAPI(title="HackTheBruh Markets API")


def _create_supabase_client():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise HTTPException(
            status_code=503,
            detail="Markets API is unavailable: Supabase is not configured.",
        )

    parsed_url = urlsplit(supabase_url)
    path = parsed_url.path.rstrip("/")
    if path.endswith("/rest/v1"):
        supabase_url = urlunsplit(parsed_url._replace(path=path[:-len("/rest/v1")]))
    return create_client(supabase_url, supabase_key)


@app.get("/markets")
def get_markets() -> list[dict[str, Any]]:
    try:
        response = (
            _create_supabase_client()
            .table("research_markets")
            .select("*")
            .execute()
        )
        return response.data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch markets from Supabase")
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch markets from Supabase.",
        ) from exc


def _fetch_all(query, page_size: int = 1000):
    """Page through a Supabase query with a deterministic order already applied."""
    rows = []
    offset = 0
    while True:
        batch = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += page_size


@app.get("/markets/{market_id}/wallets")
def get_market_wallets(market_id: str) -> dict[str, Any]:
    supabase = _create_supabase_client()
    try:
        response = (
            supabase.table("research_trades")
            .select("wallet")
            .eq("market_id", market_id)
            .not_.is_("wallet", "null")
            .order("wallet")
            .limit(1000)
            .execute()
        )

        # Remove duplicate wallet IDs
        wallet_ids = list(dict.fromkeys(
            row["wallet"] for row in response.data
        ))[:]

        return {
            "market_id": market_id,
            "wallet_ids": wallet_ids,
            "count": len(wallet_ids)
        }

    except Exception as exc:
        logger.exception("Failed to fetch wallets for market %s", market_id)
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch market wallets from Supabase.",
        ) from exc


@app.get('/wallets/{wallet_id}/stats')
def get_wallet_stats(wallet_id: str, cutoff: int | None = None):
    """Historical wallet metrics. cutoff is an optional Unix timestamp in seconds."""

    if cutoff is None:
        cutoff = int(datetime.now(timezone.utc).timestamp())

    db = _create_supabase_client()
    
    db = _create_supabase_client()
    try:
        q = (db.table('research_returns')
             .select('wallet,market_id,economic_cluster_id,available_at,'
                     'reported_realized_pnl_usdc,estimated_entry_basis_usdc,usable')
             .eq('wallet', wallet_id).eq('usable', True)
             .order('market_id'))
        
        # if cutoff is not None:
        #     q = q.lte('available_at', cutoff)

        returns = _fetch_all(q)

        valid = [r for r in returns
                 if r['reported_realized_pnl_usdc'] is not None
                 and r['estimated_entry_basis_usdc'] is not None
                 and float(r['estimated_entry_basis_usdc']) > 0
                 and r['available_at'] is not None]
        if not valid:
            raise HTTPException(status_code=404, detail='No usable completed returns for this wallet')

        # One return per market is expected in the provided schema.
        pnl = sum(float(r['reported_realized_pnl_usdc']) for r in valid)
        basis = sum(float(r['estimated_entry_basis_usdc']) for r in valid)
        profitable = sum(float(r['reported_realized_pnl_usdc']) > 0 for r in valid)
        independent = len({r['economic_cluster_id'] or r['market_id'] for r in valid})
        confidence = independent / (independent + 20)

        # A settlement edge is only estimable for buy-only markets with known labels.
        # This is a proxy, conditional on the trade feed being complete and buys
        # representing positions held to resolution. Exclude markets with any SELL.
        market_ids = list({r['market_id'] for r in valid})
        market_rows = []
        trade_rows = []
        for i in range(0, len(market_ids), 100):
            ids = market_ids[i:i + 100]
            mq = (db.table('research_markets')
                  .select('dataset_key,market_id,yes_outcome,label_available_at')
                  .in_('market_id', ids).order('market_id').order('dataset_key'))
            market_rows.extend(_fetch_all(mq))
            tq = (db.table('research_trades')
                  .select('dataset_key,market_id,source_row,side,outcome,size_shares,price,observed_at')
                  .eq('wallet', wallet_id).in_('market_id', ids)
                  .order('market_id').order('dataset_key').order('source_row'))
            if cutoff is not None:
                tq = tq.lte('observed_at', cutoff)
            trade_rows.extend(_fetch_all(tq))

        from collections import defaultdict
        market_map = defaultdict(list)
        for m in market_rows:
            if m['yes_outcome'] in (0, 1) and m['label_available_at'] is not None:
                if cutoff is None or m['label_available_at'] <= cutoff:
                    market_map[(m['dataset_key'], m['market_id'])].append(m)
        grouped = defaultdict(list)
        for t in trade_rows:
            grouped[(t['dataset_key'], t['market_id'])].append(t)

        weighted_edge_sum = 0.0
        eligible_shares = 0.0
        edge_markets = 0
        for key_, trades in grouped.items():
            labels = market_map.get(key_, [])
            if len(labels) != 1 or not trades:
                continue
            if any(str(t['side']).upper() != 'BUY' for t in trades):
                continue
            outcome_yes = labels[0]['yes_outcome'] == 1
            local_sum, local_shares = 0.0, 0.0
            for t in trades:
                outcome = str(t['outcome']).upper()
                if outcome not in ('YES', 'NO') or t['price'] is None or t['size_shares'] is None:
                    local_shares = 0
                    break
                price, shares = float(t['price']), float(t['size_shares'])
                if not (0 <= price <= 1 and shares > 0):
                    local_shares = 0
                    break
                won = outcome_yes if outcome == 'YES' else not outcome_yes
                local_sum += shares * (float(won) - price)
                local_shares += shares
            if local_shares:
                weighted_edge_sum += local_sum
                eligible_shares += local_shares
                edge_markets += 1

        return {
            'wallet': wallet_id,
            'cutoff': cutoff,
            'realized_pnl_usdc': round(pnl, 4),
            'estimated_roi': round(pnl / basis, 6),
            'profitable_market_rate': round(profitable / len(valid), 6),
            'completed_markets': len(valid),
            'independent_resolved_markets': independent,
            'confidence_weight': round(confidence, 6),
            'market_relative_edge_proxy': (
                round(weighted_edge_sum / eligible_shares, 6)
                if eligible_shares else None
            ),
            'edge_eligible_markets': edge_markets,
            'edge_method': 'share-weighted settled BUY-only trades; assumes complete trade history',
            'notes': 'ROI uses estimated entry basis; profitable_market_rate is not trade win rate.'
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('Wallet stats calculation failed')
        raise HTTPException(status_code=502, detail='Failed to calculate wallet stats') from exc


# Hard-criteria skill classification. Benchmark values must be computed from
# comparable historical peers BEFORE the classification cutoff.
from pydantic import BaseModel, Field


class ClassifyRequest(BaseModel):
    benchmark: dict[str, float]
    cutoff: int | None = Field(default=None, gt=0)
    minimum_confidence: float = Field(default=0.6, ge=0, le=1)


class PeerBenchmark(BaseModel):
    realized_pnl_usdc: float
    roi: float
    profitable_market_rate: float = Field(ge=0, le=1)
    market_relative_edge: float = Field(ge=-1, le=1)


class SkillClassificationRequest(BaseModel):
    benchmark: PeerBenchmark
    cutoff: int | None = None
    minimum_confidence: float = Field(default=0.60, ge=0, le=1)


def classify_wallet_skill(stats: dict[str, Any], benchmark: PeerBenchmark,
                          minimum_confidence: float = 0.60) -> dict[str, Any]:
    """Strict rule: every comparable metric must beat the benchmark.

    Missing edge is treated as failing eligibility, not as evidence of poor skill.
    """
    comparisons = {
        'realized_pnl': stats['realized_pnl_usdc'] > benchmark.realized_pnl_usdc,
        'roi': stats['estimated_roi'] > benchmark.roi,
        'win_rate': stats['profitable_market_rate'] > benchmark.profitable_market_rate,
        'market_relative_edge': (
            stats['market_relative_edge_proxy'] is not None
            and stats['market_relative_edge_proxy'] > benchmark.market_relative_edge
        ),
    }
    confidence_passed = stats['confidence_weight'] >= minimum_confidence
    qualified = all(comparisons.values()) and confidence_passed
    return {
        'wallet': stats['wallet'],
        'classification': 'skilled' if qualified else 'unskilled',
        'confidence_weight': stats['confidence_weight'],
        'confidence_passed': confidence_passed,
        'metrics_passed': comparisons,
        'metrics_passed_count': sum(comparisons.values()),
        'missing_edge': stats['market_relative_edge_proxy'] is None,
        'note': ('Unskilled means not qualified under this rule; '
                 'missing edge or limited history is not proof of poor skill.'),
    }


@app.post('/wallets/{wallet_id}/classify')
def classify_wallet(wallet_id: str, payload: SkillClassificationRequest):
    stats = get_wallet_stats(wallet_id, cutoff=payload.cutoff)
    return classify_wallet_skill(
        stats, payload.benchmark, payload.minimum_confidence
    )


@app.get("/test")
def test_endpoint() -> list[dict[str, Any]]:
    try:
        response = (
            _create_supabase_client()
            .table("research_returns")
            .select("*")
            .eq("wallet", "0x00c0b7e26a54958c0a82e61eb87525e06cb8c91e")
            .limit(1)
            .execute()
        )
        return response.data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch test wallet returns from Supabase")
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch test wallet returns from Supabase.",
        ) from exc
