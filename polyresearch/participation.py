"""Train on 100 earlier markets and predict next-week participation in later markets."""

import argparse
import bisect
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .active_wallets import rank_wallets
from .artifacts import manifest
from .backtest import logit, sigmoid
from .dataset import dump, gzread, read_table, table
from .position_evidence import OUTPUT as RETURN_DATASET
from .research import iso, timestamp
from .wallet_metrics import DATASET, mean

LATER_DATASET = Path("datasets/finance/resolved-20-2026-01/v1")
OUTPUT = Path("analysis/participation/2026-01/v1")
FIT_AT = timestamp("2026-01-01")
GROUPS = ("skilled_proxy", "unskilled_proxy", "unknown")
CATEGORIES = ("equities_and_corporate", "rates_and_macro", "ipos_and_deals", "commodities", "etfs_and_digital_finance")
FEATURES = ("recent_group_fraction", "log_recent_all_wallets", "log_market_age_days", "log_scheduled_remaining_days", *CATEGORIES)


def groups_at(returns, cutoff, min_markets=5):
    """Above positive peers' mean in a majority of >=5 available earlier markets.

    Labels are provisional profitability groups, never statistically proven skill.
    Unknown clock/basis or insufficient history cannot become an unskilled label.
    """
    markets = defaultdict(list)
    for row in returns:
        if str(row["usable_return_proxy"]).lower() != "true" or int(row["available_at"]) >= cutoff:
            continue
        markets[row["economic_cluster_id"]].append(row)
    wallets = defaultdict(list)
    for rows in markets.values():
        winners = [float(r["reported_return_proxy"]) for r in rows if float(r["reported_realized_pnl_usdc"]) > 0]
        threshold = mean(winners)
        if threshold is None:
            continue  # No winner mean: no comparison evidence from this market.
        for row in rows:
            value = float(row["reported_return_proxy"])
            wallets[row["wallet"]].append((value, value > threshold))
    result = {}
    for wallet, values in wallets.items():
        n = len(values)
        fraction = mean([int(above) for _, above in values])
        result[wallet] = {"group": "unknown" if n < min_markets else "skilled_proxy" if fraction > .5 else "unskilled_proxy",
                          "earlier_comparable_markets": n, "fraction_above_winner_mean": fraction,
                          "mean_reported_return_proxy": mean([v for v, _ in values])}
    return result


def load_trades(path):
    # Retain only needed fields; one large market need not load full raw JSON into memory.
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = [(int(r["timestamp"]), r["wallet"], r["side"], r["outcome"].lower()) for r in csv.DictReader(handle)]
    rows.sort(key=lambda r: r[0])
    return rows, [r[0] for r in rows]


def actions(trades, times, start, end):
    """Distinct wallets, with side and token preserved. End is exclusive."""
    sides = {"BUY": set(), "SELL": set()}
    tokens = {(side, token): set() for side in sides for token in ("yes", "no")}
    for _, wallet, side, token in trades[bisect.bisect_left(times, start):bisect.bisect_left(times, end)]:
        if side not in sides or token not in ("yes", "no"):
            raise ValueError("Unexpected trade side/outcome")
        sides[side].add(wallet)
        tokens[(side, token)].add(wallet)
    return sides, tokens


def window_rows(market, cutoff, horizon, candidates, groups, trades, times, closed_at):
    end = cutoff + horizon
    before, _ = actions(trades, times, cutoff-horizon, cutoff)
    after, token_actions = actions(trades, times, cutoff, min(end, closed_at))
    eligible = {r["wallet"] for r in candidates if int(r["first_trade_at"]) < cutoff}
    by_group = {group: {w for w in eligible if groups.get(w, {}).get("group", "unknown") == group} for group in GROUPS}
    prior_all = len(before["BUY"] | before["SELL"])
    opened = timestamp(market["trading_start"])
    scheduled = timestamp(market["scheduled_end_date"]) if market["scheduled_end_date"] else cutoff
    rows, token_rows = [], []
    for group, members in by_group.items():
        for side in ("BUY", "SELL"):
            actual = len(after[side] & members)
            prior = len(before[side] & members)
            row = {"market_id": market["market_id"], "economic_cluster_id": market["economic_cluster_id"],
                   "forecast_at": cutoff, "forecast_at_utc": iso(cutoff), "window_end": end,
                   "group": group, "side": side, "group_size": len(members),
                   "actual_wallets": actual, "recent_wallets": prior,
                   "recent_group_fraction": prior/len(members) if members else 0,
                   "log_recent_all_wallets": math.log1p(prior_all),
                   "log_market_age_days": math.log1p(max(0, cutoff-opened)/86400),
                   "log_scheduled_remaining_days": math.log1p(max(0, scheduled-cutoff)/86400),
                   **{category: int(market["subfield"] == category) for category in CATEGORIES}}
            rows.append(row)
            for token in ("yes", "no"):
                token_rows.append({"market_id": market["market_id"], "forecast_at": cutoff, "group": group,
                                   "side": side, "token": token, "actual_wallets": len(token_actions[(side, token)] & members)})
    coverage = {"market_id": market["market_id"], "forecast_at": cutoff, "window_end": end,
                "eligible_candidate_wallets": len(eligible),
                "actual_all_wallet_participants": len(after["BUY"] | after["SELL"]),
                "actual_candidate_participants": len((after["BUY"] | after["SELL"]) & eligible),
                "actual_outside_candidate_participants": len((after["BUY"] | after["SELL"]) - eligible),
                "trading_exposure_seconds": max(0, min(end, closed_at)-cutoff),
                "group_sizes": {g: len(s) for g, s in by_group.items()}}
    return rows, token_rows, coverage


def examples(dataset, candidates, returns, fit_at, horizon, split, min_markets):
    rows, tokens, coverage, exclusions = [], [], [], []
    for market in read_table(dataset / "markets.csv"):
        folder = dataset / market["folder"]
        if not timestamp(market["trading_start"]):
            raise ValueError("Missing opening timestamp")
        raw = gzread(folder / "raw/market.json.gz")
        closed_at = timestamp(raw["closedTime"])
        opened = timestamp(market["trading_start"])
        if split == "train":
            if int(market["label_available_at"]) >= fit_at:
                raise ValueError("Earlier market not resolved before fit cutoff")
            first = max(opened+86400, timestamp("2025-08-01"))
            cutoffs = range(first, min(closed_at, fit_at-horizon+1), horizon)
        else:
            first = max(opened+86400, fit_at)
            cutoffs = [first] if first < closed_at else []
        trades, times = load_trades(folder / "wallet_trade_legs.csv.gz")
        made = 0
        for cutoff in cutoffs:
            if split == "train" and cutoff+horizon > fit_at:
                raise ValueError("Future training action label")
            group_map = groups_at(returns, cutoff, min_markets)
            result, detail, cov = window_rows(market, cutoff, horizon, candidates, group_map, trades, times, closed_at)
            if not cov["eligible_candidate_wallets"]:
                continue
            for row in result:
                row["split"] = split
            rows.extend(result)
            tokens.extend(detail)
            coverage.append(cov)
            made += 1
        if not made:
            exclusions.append({"market_id": market["market_id"], "split": split,
                               "reason": "no prediction while open with earlier known candidate wallets"})
    return rows, tokens, coverage, exclusions


def fit_rate_model(rows, penalty=.01, iterations=700):
    """Regularized binomial count model; all scaling and labels use training rows only."""
    rows = [r for r in rows if r["group_size"] > 0]
    if not rows:
        return None
    centers = [mean([r[f] for r in rows]) for f in FEATURES]
    scales = [math.sqrt(mean([(r[f]-c)**2 for r in rows])) or 1 for f, c in zip(FEATURES, centers)]
    xs = [[1]+[(r[f]-c)/s for f,c,s in zip(FEATURES,centers,scales)] for r in rows]
    mass = sum(r["group_size"] for r in rows)
    total = sum(r["actual_wallets"] for r in rows)
    rate = (total+1)/(mass+2)
    beta = [logit(rate)] + [0.0]*len(FEATURES)
    for _ in range(iterations):
        gradient = [0.0]+[penalty*b for b in beta[1:]]
        for row, x in zip(rows, xs):
            p = sigmoid(sum(a*b for a,b in zip(x,beta)))
            error = (row["group_size"]*p-row["actual_wallets"])/mass
            for j, value in enumerate(x):
                gradient[j] += error*value
        beta = [b-.5*g for b,g in zip(beta,gradient)]
        if max(map(abs,gradient)) < 1e-8:
            break
    return {"features": list(FEATURES), "centers": centers, "scales": scales, "coefficients": beta,
            "historical_rate": rate, "fit_rows": len(rows), "wallet_opportunities": mass,
            "observed_actions": total, "l2_penalty": penalty}


def predict_count(model, row):
    if not row["group_size"]:
        return 0.0
    if model is None:
        raise ValueError("No training model for a nonempty prediction group")
    x = [1]+[(row[f]-c)/s for f,c,s in zip(model["features"],model["centers"],model["scales"])]
    return row["group_size"]*sigmoid(sum(a*b for a,b in zip(x,model["coefficients"])))


def metrics(rows, prediction):
    errors = [r[prediction]-r["actual_wallets"] for r in rows]
    return {"count_rows": len(rows), "mae_wallets": mean([abs(e) for e in errors]),
            "rmse_wallets": math.sqrt(mean([e*e for e in errors])) if errors else None,
            "bias_wallets": mean(errors), "actual_sum": sum(r["actual_wallets"] for r in rows),
            "predicted_sum": sum(r[prediction] for r in rows)}


def build(earlier=DATASET, later=LATER_DATASET, return_dataset=RETURN_DATASET, out=OUTPUT,
          fit_at=FIT_AT, horizon_days=7, top=100, min_markets=5):
    horizon = int(horizon_days*86400)
    if horizon <= 0 or top <= 0 or min_markets <= 0:
        raise ValueError("Positive horizon, candidate count and minimum history required")
    for dataset in (earlier, later):
        if not json.loads((dataset / "validation.json").read_text())["passed"]:
            raise ValueError("Cannot train/evaluate incomplete market data")
    if json.loads((return_dataset / "summary.json").read_text())["errors"]:
        raise ValueError("Incomplete return evidence")
    earlier_ids = {r["economic_cluster_id"] for r in read_table(earlier / "markets.csv")}
    if earlier_ids & {r["economic_cluster_id"] for r in read_table(later / "markets.csv")}:
        raise ValueError("Economic group overlaps training and test sets")
    settings = {"earlier": earlier.as_posix(), "later": later.as_posix(), "return_dataset": return_dataset.as_posix(),
                "fit_at": fit_at, "horizon_days": horizon_days, "candidate_wallets": top, "minimum_earlier_markets": min_markets,
                "group_rule": "return above positive peers' mean in >50% of >=5 comparable earlier markets; proxy only",
                "training_origins": "weekly after first 24 hours, no earlier than Aug 1 2025; complete windows before fit",
                "test_origins": "one per market: max(fit time, trading start + 24h)",
                "side_definition": "distinct wallets buying/selling either token, with token detail retained",
                "model": "separate regularized binomial count models per group and side; pooled-side fallback; penalty .01"}
    out.mkdir(parents=True, exist_ok=True)
    if (out / "config.json").exists() and json.loads((out / "config.json").read_text()) != settings:
        raise ValueError("Existing experiment settings differ; choose a new output directory")
    dump(out / "config.json", settings)
    ranked, _ = rank_wallets(earlier, fit_at)
    candidates = ranked[:top]
    returns = read_table(return_dataset / "wallet_market_returns.csv.gz")
    fit_groups = groups_at(returns, fit_at, min_markets)
    candidate_rows = [{**c, **fit_groups.get(c["wallet"], {"group": "unknown", "earlier_comparable_markets": 0})} for c in candidates]
    table(out / "candidate_wallets.csv", candidate_rows, sorted({k for r in candidate_rows for k in r}))
    train, _, train_cov, excluded_train = examples(earlier, candidates, returns, fit_at, horizon, "train", min_markets)
    if not train:
        raise ValueError("No earlier participation windows")
    models = {}
    for side in ("BUY", "SELL"):
        pool = [r for r in train if r["side"] == side]
        models["pooled_"+side] = fit_rate_model(pool)
        for group in GROUPS:
            models[group+"_"+side] = fit_rate_model([r for r in pool if r["group"] == group])
    dump(out / "model.json", {"fit_at": fit_at, "models": models, "fitted_without_test_labels": True})
    # Build test labels only after all model parameters have been fitted and saved.
    test, tokens, coverage, excluded_test = examples(later, candidates, returns, fit_at, horizon, "test", min_markets)
    for row in test:
        model = models[row["group"]+"_"+row["side"]] or models["pooled_"+row["side"]]
        row["model_predicted_wallets"] = predict_count(model, row)
        row["historical_rate_predicted_wallets"] = row["group_size"]*model["historical_rate"]
        row["recent_count_predicted_wallets"] = row["recent_wallets"]
        row["zero_predicted_wallets"] = 0.0
        row["absolute_error_wallets"] = abs(row["model_predicted_wallets"]-row["actual_wallets"])
    table(out / "training_counts.csv.gz", train, list(train[0]))
    table(out / "predictions.csv", test, list(test[0]) if test else ["market_id"])
    table(out / "observed_token_counts.csv", tokens, list(tokens[0]) if tokens else ["market_id"])
    table(out / "coverage.csv", [{**{k:v for k,v in r.items() if k != "group_sizes"},
                                   **{g+"_size": n for g,n in r["group_sizes"].items()}} for r in coverage],
          ["market_id", "forecast_at", "window_end", "eligible_candidate_wallets", "actual_all_wallet_participants",
           "actual_candidate_participants", "actual_outside_candidate_participants", "trading_exposure_seconds",
           *[g+"_size" for g in GROUPS]])
    table(out / "excluded_markets.csv", excluded_train+excluded_test, ["market_id", "split", "reason"])
    measures = ("model_predicted_wallets", "historical_rate_predicted_wallets", "recent_count_predicted_wallets", "zero_predicted_wallets")
    grouped = {g: {p: metrics([r for r in test if r["group"] == g], p) for p in measures} for g in GROUPS}
    windows = [{"market_id": c["market_id"], "week": str(datetime.fromtimestamp(c["forecast_at"], timezone.utc).isocalendar()[:2])} for c in coverage]
    known = [r for r in test if r["group"] != "unknown"]
    def error_breakdown(key):
        blocks = defaultdict(list)
        for row in known:
            value = row["market_id"] if key == "market_id" else str(datetime.fromtimestamp(row["forecast_at"], timezone.utc).isocalendar()[:2])
            blocks[value].append(row)
        return [{key: value, "markets": len({r["market_id"] for r in samples}),
                 **{p.replace("predicted_wallets", "mae"): metrics(samples, p)["mae_wallets"] for p in measures}}
                for value,samples in sorted(blocks.items())]
    market_errors, weekly_errors = error_breakdown("market_id"), error_breakdown("prediction_week")
    for name, values in (("per_market_errors.csv", market_errors), ("per_week_errors.csv", weekly_errors)):
        table(out / name, values, list(values[0]) if values else ["market_id"])
    summary = {"status": "exploratory participation test with provisional return-based labels; not validated wallet skill",
               "fit_at": iso(fit_at), "horizon_days": horizon_days,
               "earlier_source_markets": len(read_table(earlier / "markets.csv")),
               "training_markets_with_windows": len({r["market_id"] for r in train}), "training_windows": len(train_cov),
               "training_count_rows": len(train), "candidate_wallets": len(candidates),
               "groups_at_fit": dict(Counter(r["group"] for r in candidate_rows)),
               "test_source_markets": len(read_table(later / "markets.csv")), "test_windows": len(coverage),
               "test_prediction_calendar_weeks": len({w["week"] for w in windows}),
               "markets_model_lower_mae_than_historical_rate": sum(r["model_mae"] < r["historical_rate_mae"] for r in market_errors),
               "prediction_weeks_model_lower_mae_than_historical_rate": sum(r["model_mae"] < r["historical_rate_mae"] for r in weekly_errors),
               "four_requested_counts": {p: metrics(known, p) for p in measures}, "by_group": grouped,
               "coverage_participant_market_pairs": {"all_wallets": sum(c["actual_all_wallet_participants"] for c in coverage),
                                                      "candidate_wallets": sum(c["actual_candidate_participants"] for c in coverage),
                                                      "outside_candidates": sum(c["actual_outside_candidate_participants"] for c in coverage)},
               "confidence_interval": None,
               "limitations": ["Skill labels use a provider return proxy, not reconciled ROI or statistical proof",
                               "Only the frozen candidate universe is predicted; outside/new wallets reported separately",
                               "Returns use current retrospective snapshots only after their last economics timestamp; later revisions may exist",
                               "Opening/schedule/closure metadata is retrospective; no historical publication snapshots",
                               "Repeated weekly training windows are dependent; 100 markets are not thousands of independent events",
                               "Resolved-only sampling and shared economic news limit generalization",
                               "Sparse skilled-proxy activity and a small later sample limit consistency claims"]}
    dump(out / "summary.json", summary)
    manifest(out, [earlier / "manifest.json", later / "manifest.json", return_dataset / "manifest.json", Path(__file__),
                   Path(__file__).with_name("active_wallets.py"), Path(__file__).with_name("backtest.py"),
                   Path(__file__).with_name("artifacts.py")])
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--earlier", type=Path, default=DATASET)
    parser.add_argument("--later", type=Path, default=LATER_DATASET)
    parser.add_argument("--returns", type=Path, default=RETURN_DATASET)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--horizon-days", type=float, default=7)
    parser.add_argument("--fit-at", type=timestamp, default=FIT_AT)
    args = parser.parse_args()
    build(args.earlier, args.later, args.returns, args.out, args.fit_at, args.horizon_days)


if __name__ == "__main__":
    main()
