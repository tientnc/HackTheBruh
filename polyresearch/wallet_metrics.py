"""Point-in-time wallet metrics, explicit missing data, and pilot decile rankings."""

import argparse
import hashlib
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .artifacts import manifest, sha256
from .client import Client, DATA
from .dataset import dump, gzread, gzwrite, read_table, table
from .research import iso, now, timestamp

DATASET = Path("datasets/finance/resolved-100-2025/v1")
OUTPUT = Path("analysis/finance-wallets/2025-12-01/v1")
AS_OF = timestamp("2025-12-01")


def mean(values):
    return sum(values) / len(values) if values else None


def brier_skill(forecasts, benchmarks, outcomes, weights=None):
    """Compare explicit probability forecasts on identical observations.

    Trade side is not a probability forecast. Callers must supply probabilities,
    historical timestamps, and a comparable benchmark, not infer certainty from BUY.
    """
    if not (len(forecasts) == len(benchmarks) == len(outcomes)):
        raise ValueError("Forecasts, benchmarks and outcomes must align")
    if weights is None:
        weights = [1.0] * len(outcomes)
    if len(weights) != len(outcomes):
        raise ValueError("Weights must align")
    for q, p, y, weight in zip(forecasts, benchmarks, outcomes, weights):
        if not all(math.isfinite(v) for v in (q, p, y, weight)) or not (0 <= q <= 1 and 0 <= p <= 1 and y in (0, 1) and weight >= 0):
            raise ValueError("Invalid forecast, outcome or weight")
    mass = sum(weights)
    if mass <= 0:
        return {"wallet_brier": None, "market_brier": None, "brier_skill_score": None}
    own = sum(w * (q - y) ** 2 for q, y, w in zip(forecasts, outcomes, weights)) / mass
    reference = sum(w * (p - y) ** 2 for p, y, w in zip(benchmarks, outcomes, weights)) / mass
    return {"wallet_brier": own, "market_brier": reference,
            "brier_skill_score": 1 - own / reference if reference > 0 else None}


def closed_position_metrics(positions, as_of):
    """Metrics for explicitly reconciled closed positions, not a fill-derived PnL.

    Cost basis excludes the separately supplied fees/other costs. Capital is the
    explicitly supplied sum of deployed capital, not wallet balance or turnover.
    This returns metrics for supplied positions; it does not assert lifetime coverage.
    """
    pnl, capital = [], 0.0
    for row in positions:
        if int(row["available_at"]) < int(row["closed_at"]) or ("opened_at" in row and int(row["opened_at"]) > int(row["closed_at"])):
            raise ValueError("Position availability must follow closure, which must follow opening")
        if int(row["closed_at"]) >= as_of or int(row["available_at"]) >= as_of:
            continue
        if row.get("reconciled") is not True:
            raise ValueError("Closed positions must be explicitly reconciled")
        values = [float(row[k]) for k in ("proceeds_usdc", "cost_basis_usdc", "fees_usdc", "other_costs_usdc", "capital_deployed_usdc")]
        if not all(math.isfinite(v) and v >= 0 for v in values) or values[-1] <= 0:
            raise ValueError("Complete nonnegative costs and positive deployed capital required")
        proceeds, basis, fees, other, deployed = values
        pnl.append(proceeds - basis - fees - other)
        capital += deployed
    return {"reconciled_position_count": len(pnl),
            "net_realized_pnl_usdc": sum(pnl) if pnl else None,
            "roi_on_supplied_deployed_capital": sum(pnl) / capital if capital else None,
            "profitable_closed_position_win_rate": mean([int(p > 0) for p in pnl])}


def sign_randomization(values, seed=0, draws=20000):
    """Exploratory two-sided event-sign test under a sign-symmetry null.

    One sign per event, not per fill. This is not a Yale-method replication,
    a calibrated-market null, or a feasible randomized trading strategy.
    """
    values = [float(v) for v in values]
    if not values:
        return None
    if any(not math.isfinite(v) for v in values):
        raise ValueError("Event values must be finite")
    observed = abs(sum(values))
    if observed < 1e-15:
        return 1.0
    if len(values) <= 16:
        exceed = sum(abs(sum(s * v for s, v in zip(signs, values))) >= observed - 1e-12
                     for signs in itertools.product((-1, 1), repeat=len(values)))
        return exceed / (2 ** len(values))
    rng = random.Random(seed)
    exceed = 0
    for _ in range(draws):
        statistic = abs(sum(v if rng.getrandbits(1) else -v for v in values))
        exceed += statistic >= observed - 1e-12
    return (exceed + 1) / (draws + 1)


def adjusted_qvalues(pvalues, method="BY"):
    """BH or dependence-conservative BY; validity still requires valid input p-values."""
    if method not in ("BH", "BY") or any(not 0 <= p <= 1 for p in pvalues.values()):
        raise ValueError("Invalid p-values or FDR method")
    ordered = sorted(pvalues, key=lambda key: (pvalues[key], key))
    n = len(ordered)
    factor = sum(1 / rank for rank in range(1, n + 1)) if method == "BY" else 1
    previous, result = 1.0, {}
    for rank in range(n, 0, -1):
        key = ordered[rank - 1]
        previous = min(previous, pvalues[key] * n * factor / rank)
        result[key] = min(1.0, previous)
    return result


def event_evidence(root, as_of, min_lead_hours=0):
    """Equal-event evidence from historical taker fills only; labels must mature."""
    evidence, population = [], set()
    resolved_markets = 0
    for market in read_table(root / "markets.csv"):
        label_at = int(market["label_available_at"])
        if label_at >= as_of:
            continue
        resolved_markets += 1
        folder = root / market["folder"]
        population.update(row["wallet"] for row in read_table(folder / "wallets.csv"))
        trades = read_table(folder / "trades.csv.gz")
        grouped = defaultdict(list)
        for trade in trades:
            if int(trade["timestamp"]) >= as_of or int(trade["timestamp"]) >= label_at - min_lead_hours * 3600:
                continue
            grouped[trade["wallet"]].append(trade)
        for wallet, rows in grouped.items():
            total, payoff, directional, reference, late = 0.0, 0.0, 0.0, 0.0, 0
            for row in rows:
                size, price = float(row["size_shares"]), float(row["price"])
                yes_token = row["outcome"].lower() == "yes"
                token_y = int(market["yes_outcome"]) if yes_token else 1 - int(market["yes_outcome"])
                side = 1 if row["side"] == "BUY" else -1
                total += size
                payoff += side * size * (token_y - price)
                directional += side * size * (1 if yes_token else -1)
                reference += size * (price if yes_token else 1 - price)
                late += int(label_at - int(row["timestamp"]) < 86400)
            if total <= 0:
                continue
            dominant = 1 if directional > 1e-9 else -1 if directional < -1e-9 else 0
            reference_yes = reference / total
            evidence.append({"wallet": wallet, "market_id": market["market_id"],
                "economic_cluster_id": market["economic_cluster_id"], "category": market["subfield"],
                "label_available_at": label_at, "trade_rows": len(rows), "shares": total,
                "event_market_relative_edge": payoff / total,
                "settlement_payoff_proxy_usdc": payoff,
                "dominant_direction_correct": int((dominant == 1) == bool(int(market["yes_outcome"]))) if dominant else None,
                "implied_directional_success_proxy": reference_yes if dominant == 1 else 1 - reference_yes if dominant else None,
                "late_trade_fraction": late / len(rows)})
    return evidence, population, resolved_markets


def historical_pnl(response, as_of):
    points = (response.get("data") or {}).get("points", [])
    eligible = [p for p in points if int(p["timestamp"]) < as_of]
    point = max(eligible, key=lambda p: int(p["timestamp"]), default=None)
    result = {"reported_lifetime_realized_pnl_usdc": None, "pnl_observed_at": None,
              "pnl_age_seconds": None, "reported_fee_atom_usdc": None,
              "pnl_scope": "all-market historical provider report; not independently reconciled after all costs"}
    if point:
        a, b = point.get("realized_market_pnl"), point.get("realized_combo_pnl")
        if all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b)):
            result["reported_lifetime_realized_pnl_usdc"] = a + b
        result.update(pnl_observed_at=int(point["timestamp"]),
                      pnl_age_seconds=as_of - int(point["timestamp"]),
                      reported_fee_atom_usdc=point.get("fees_paid"))
    return result


def forecast_is_available(forecast, as_of):
    """All input information must precede issue time; outcomes mature later."""
    issued = int(forecast["issued_at"])
    quote = int(forecast["market_quote_at"])
    available = int(forecast["market_quote_available_at"])
    return quote <= available <= issued < int(forecast["outcome_available_at"]) < as_of


def build(root, out, as_of=AS_OF, min_events=5, prior_events=10, enrich=False, evidence_path=None,
          min_lead_hours=0, workers=4):
    settings = {"as_of": as_of, "dataset": root.as_posix(), "min_events_for_pilot_ranking": min_events,
                "shrinkage_prior_events": prior_events, "minimum_lead_hours": min_lead_hours,
                "score": "equal-event mean signed settlement edge, shrunk toward zero",
                "fdr_diagnostic": "BY at 5%; event-sign symmetry null; diagnostic only",
                "enrich_reported_pnl": enrich,
                "audited_evidence_sha256": sha256(evidence_path) if evidence_path else None}
    out.mkdir(parents=True, exist_ok=True)
    if (out / "config.json").exists() and json.loads((out / "config.json").read_text()) != settings:
        raise ValueError("Existing output uses different settings; choose a new path")
    dump(out / "config.json", settings)
    observations, population, market_count = event_evidence(root, as_of, min_lead_hours)
    by_wallet = defaultdict(list)
    for row in observations:
        by_wallet[row["wallet"]].append(row)
    metrics, category_rows = [], []
    for wallet in sorted(population):
        rows = sorted(by_wallet[wallet], key=lambda row: row["label_available_at"])
        # The source selection guarantees unique economic groups, but verify again here.
        if len({r["economic_cluster_id"] for r in rows}) != len(rows):
            raise ValueError("Repeated economic cluster in wallet evidence")
        edges = [r["event_market_relative_edge"] for r in rows]
        n = len(edges)
        average = mean(edges)
        midpoint = n // 2
        halves = [mean(edges[:midpoint]), mean(edges[midpoint:])]
        seed = int(hashlib.sha256(wallet.encode()).hexdigest()[:16], 16)
        eligible = n >= min_events
        correct = [r["dominant_direction_correct"] for r in rows if r["dominant_direction_correct"] is not None]
        implied = [r["implied_directional_success_proxy"] for r in rows if r["implied_directional_success_proxy"] is not None]
        record = {"wallet": wallet, "as_of": as_of, "resolved_markets_in_sample": n,
                  "taker_trade_rows": sum(r["trade_rows"] for r in rows),
                  "market_relative_edge": average,
                  "ranking_score": average * n / (n + prior_events) if n else None,
                  "directional_event_win_rate": mean(correct), "expected_directional_win_rate_proxy": mean(implied),
                  "sample_settlement_payoff_proxy_usdc": sum(r["settlement_payoff_proxy_usdc"] for r in rows) if n else None,
                  "historical_first_half_edge": halves[0], "historical_second_half_edge": halves[1],
                  "consistency": "both_positive" if midpoint >= 3 and n-midpoint >= 3 and all(h > 0 for h in halves)
                                 else "mixed_or_negative" if midpoint >= 3 and n-midpoint >= 3 else "insufficient_history",
                  "leave_one_event_out_min_edge": min((sum(edges)-edge)/(n-1) for edge in edges) if n > 1 else None,
                  "late_trade_fraction": mean([r["late_trade_fraction"] for r in rows]),
                  "pilot_rank_eligible": eligible, "cohort": "unranked", "rank": None,
                  "p_value_sign_diagnostic": sign_randomization(edges, seed) if eligible else None,
                  "q_value_by_diagnostic": None, "statistical_skill": "not_established",
                  "reported_lifetime_realized_pnl_usdc": None, "pnl_observed_at": None, "pnl_age_seconds": None,
                  "net_realized_pnl_usdc": None, "roi_on_supplied_deployed_capital": None,
                  "profitable_closed_position_win_rate": None, "brier_skill_score": None,
                  "metric_limitations": "PnL/ROI need reconciled costs and capital; BSS needs explicit probabilities; ranking uses selected-market taker evidence"}
        metrics.append(record)
        categories = defaultdict(list)
        for row in rows:
            categories[row["category"]].append(row["event_market_relative_edge"])
        for category, values in sorted(categories.items()):
            category_rows.append({"wallet": wallet, "category": category, "resolved_markets": len(values),
                                  "market_relative_edge": mean(values),
                                  "ranking_score": mean(values)*len(values)/(len(values)+prior_events)})
    ranking = sorted((r for r in metrics if r["pilot_rank_eligible"]), key=lambda r: (-r["ranking_score"], r["wallet"]))
    decile_size = len(ranking) // 10
    qvalues = adjusted_qvalues({r["wallet"]: r["p_value_sign_diagnostic"] for r in ranking})
    for rank, row in enumerate(ranking, 1):
        row.update(rank=rank, q_value_by_diagnostic=qvalues[row["wallet"]],
                   cohort="top_decile" if rank <= decile_size else "bottom_decile" if decile_size and rank > len(ranking)-decile_size else "middle")
    if enrich:
        def fetch(wallet):
            path = out / "raw" / "pnl" / f"{wallet}.json.gz"
            if not path.exists():
                try:
                    result = Client(timeout=30, retries=2).get(DATA, "/v2/user-pnl", user=wallet, interval="max", fidelity="1d")
                except Exception as error:
                    result = {"data": None, "collection_error": str(error)}
                gzwrite(path, result)
            return wallet, gzread(path)
        pnl_responses = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [pool.submit(fetch, r["wallet"]) for r in ranking]
            for job in as_completed(jobs):
                wallet, response = job.result()
                pnl_responses[wallet] = response
        for row in ranking:
            row.update(historical_pnl(pnl_responses[row["wallet"]], as_of))
            if pnl_responses[row["wallet"]].get("collection_error"):
                row["pnl_collection_error"] = pnl_responses[row["wallet"]]["collection_error"]
    # An optional audited evidence input makes unavailable metrics usable without
    # inventing position PnL, capital denominators, or subjective probabilities.
    evidence = json.loads(evidence_path.read_text()) if evidence_path else {}
    ledger = defaultdict(list)
    for position in evidence.get("closed_positions", []):
        ledger[position["wallet"].lower()].append(position)
    forecasts = defaultdict(list)
    for forecast in evidence.get("forecasts", []):
        if forecast_is_available(forecast, as_of):
            forecasts[forecast["wallet"].lower()].append(forecast)
    for row in metrics:
        if row["wallet"] in ledger:
            row.update(closed_position_metrics(ledger[row["wallet"]], as_of))
            row["reconciled_pnl_scope"] = "supplied reconciled positions only; not guaranteed lifetime coverage"
        samples = forecasts[row["wallet"]]
        if samples:
            event_counts = Counter(f["economic_cluster_id"] for f in samples)
            row.update(brier_skill([float(f["wallet_probability"]) for f in samples],
                                   [float(f["market_probability"]) for f in samples], [int(f["outcome"]) for f in samples],
                                   [1/event_counts[f["economic_cluster_id"]] for f in samples]))
    table(out / "wallet_metrics.csv", metrics, sorted({key for row in metrics for key in row}))
    table(out / "event_evidence.csv.gz", observations, list(observations[0]) if observations else ["wallet"])
    table(out / "category_metrics.csv", category_rows, ["wallet", "category", "resolved_markets", "market_relative_edge", "ranking_score"])
    dump(out / "cohorts.json", {"as_of": as_of, "decile_size": decile_size,
                               "members": {name: [r["wallet"] for r in ranking if r["cohort"] == name]
                                           for name in ("top_decile", "middle", "bottom_decile")},
                               "ranking": [{k: r[k] for k in ("wallet", "rank", "ranking_score", "resolved_markets_in_sample", "cohort")} for r in ranking]})
    summary = {"built_at": now(), "as_of": iso(as_of), "source_markets_resolved_before_cutoff": market_count,
               "wallets_seen_in_earlier_markets": len(population), "pilot_eligible_wallets": len(ranking),
               "wallets_per_decile": decile_size,
               "reported_historical_pnl_available": sum(r.get("reported_lifetime_realized_pnl_usdc") is not None for r in ranking),
               "sign_diagnostic_by_q_le_005": sum(r["q_value_by_diagnostic"] <= .05 for r in ranking),
               "statistically_confirmed_skilled_wallets": 0,
               "status": "pilot rankings; sign-symmetry diagnostic assumptions and out-of-sample persistence not established",
               "missing_net_roi_or_bss": {"net_realized_pnl": sum(r["net_realized_pnl_usdc"] is None for r in ranking),
                                          "roi": sum(r["roi_on_supplied_deployed_capital"] is None for r in ranking),
                                          "bss": sum(r["brier_skill_score"] is None for r in ranking)},
               "ties_at_top_boundary": bool(decile_size and ranking[decile_size-1]["ranking_score"] == ranking[decile_size]["ranking_score"]),
               "fdr_note": "BY controls dependence only with valid p-values; sign-symmetry null is an exploratory assumption, not verified skill"}
    dump(out / "summary.json", summary)
    sources = [root / "manifest.json", root / "markets.csv", Path(__file__), Path(__file__).with_name("artifacts.py")]
    if evidence_path:
        sources.append(evidence_path)
    manifest(out, sources)
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--as-of", type=timestamp, default=AS_OF)
    parser.add_argument("--min-events", type=int, default=5)
    parser.add_argument("--prior-events", type=float, default=10)
    parser.add_argument("--min-lead-hours", type=float, default=0)
    parser.add_argument("--enrich-pnl", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.min_events < 1 or not math.isfinite(args.prior_events) or args.prior_events < 0 or not math.isfinite(args.min_lead_hours) or args.min_lead_hours < 0:
        parser.error("Invalid minimum evidence, shrinkage, or lead-time setting")
    build(args.dataset, args.out, args.as_of, args.min_events, args.prior_events,
          args.enrich_pnl, args.evidence, args.min_lead_hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
