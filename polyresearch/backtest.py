"""Exploratory final-outcome forecasts using frozen wallet cohorts and later markets."""

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import manifest
from .dataset import dump, read_table, table
from .research import iso, timestamp
from .wallet_metrics import DATASET, OUTPUT as WALLET_OUTPUT, brier_skill, mean

OUTPUT = Path("analysis/finance-backtest/2025-12/v1")
TEST_START = timestamp("2025-12-15")


def sigmoid(value):
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    e = math.exp(value)
    return e / (1 + e)


def logit(p):
    p = min(1 - 1e-6, max(1e-6, p))
    return math.log(p / (1 - p))


def predict(p, features, coefficients):
    offset = sum(x * coefficient for x, coefficient in zip(features, coefficients))
    return p if abs(offset) < 1e-15 else sigmoid(logit(p) + offset)


def fit(rows, fields, penalty=.1, iterations=2000):
    """Regularized logistic adjustment to quoted odds, no fitted intercept.

    All labels used here must be available before the model fit cutoff.
    """
    if not rows:
        raise ValueError("No earlier calibration forecasts with mature labels")
    beta = [0.0] * len(fields)
    for _ in range(iterations):
        gradient = [penalty * value for value in beta]
        for row in rows:
            x = [row[field] for field in fields]
            error = predict(row["market_probability"], x, beta) - row["yes_outcome"]
            for j in range(len(beta)):
                gradient[j] += error * x[j] / len(rows)
        beta = [value - .25 * slope for value, slope in zip(beta, gradient)]
        if max(map(abs, gradient), default=0) < 1e-10:
            break
    return beta


def price_at(rows, yes_token, cutoff, max_age_seconds=86400):
    eligible = [r for r in rows if r["token_id"] == yes_token and int(r["resolution_seconds"]) > 0
                and int(r["available_at"]) <= cutoff
                and 0 <= cutoff-int(r["available_at"]) <= max_age_seconds]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (int(row["available_at"]), int(row["timestamp"])))


def flow_features(trades, cutoff, cohorts, window_seconds=7*86400, cap_shares=1000):
    net = Counter()
    for row in trades:
        if not cutoff-window_seconds <= int(row["timestamp"]) < cutoff:
            continue
        sign = (1 if row["outcome"].lower() == "yes" else -1) * (1 if row["side"] == "BUY" else -1)
        net[row["wallet"]] += sign * float(row["size_shares"])
    bounded = {wallet: max(-1, min(1, amount/cap_shares)) for wallet, amount in net.items()}
    result = {}
    for name in ("top_decile", "bottom_decile"):
        members = cohorts["members"][name]
        result[name + "_flow"] = sum(bounded.get(wallet, 0) for wallet in members) / len(members) if members else 0.0
        result[name + "_active_wallets"] = sum(abs(net.get(wallet, 0)) > 1e-12 for wallet in members)
    active = [v for v in bounded.values() if abs(v) > 1e-12]
    result["all_wallet_flow"] = mean(active) if active else 0.0
    return result


def score(rows, probability_field):
    if not rows:
        return {"markets": 0, "brier_score": None, "log_loss": None, "brier_skill_vs_market": None}
    probs = [row[probability_field] for row in rows]
    result = brier_skill(probs, [r["market_probability"] for r in rows], [r["yes_outcome"] for r in rows])
    loss = mean([-r["yes_outcome"]*math.log(min(1-1e-6,max(1e-6,p)))
                 -(1-r["yes_outcome"])*math.log(1-min(1-1e-6,max(1e-6,p))) for r,p in zip(rows,probs)])
    return {"markets": len(rows), "brier_score": result["wallet_brier"], "log_loss": loss,
            "brier_skill_vs_market": result["brier_skill_score"]}


def build(dataset, wallet_output, out, test_start=TEST_START, lead_hours=24, max_price_age_hours=24, penalty=.1):
    cohorts = json.loads((wallet_output / "cohorts.json").read_text())
    cohort_at = int(cohorts["as_of"])
    if cohort_at >= test_start:
        raise ValueError("Ranking cutoff must precede model fit/test cutoff")
    if not cohorts["decile_size"]:
        raise ValueError("Too few eligible wallets to form nonempty deciles")
    out.mkdir(parents=True, exist_ok=True)
    settings = {"dataset": dataset.as_posix(), "wallet_metrics": wallet_output.as_posix(),
                "cohort_cutoff": cohort_at, "model_fit_cutoff": test_start,
                "forecast_rule": "reported scheduled end minus lead_hours; retrospective metadata",
                "lead_hours": lead_hours, "max_price_age_hours": max_price_age_hours,
                "flow_window_days": 7, "wallet_cap_shares": 1000, "logistic_l2_penalty": penalty}
    if (out / "config.json").exists() and json.loads((out / "config.json").read_text()) != settings:
        raise ValueError("Existing experiment has different settings; choose a new output path")
    dump(out / "config.json", settings)
    forecasts, exclusions = [], []
    for market in read_table(dataset / "markets.csv"):
        label_at = int(market["label_available_at"])
        if label_at <= cohort_at:
            continue
        folder = dataset / market["folder"]
        if not market["scheduled_end_date"]:
            exclusions.append({"market_id": market["market_id"], "reason": "missing_schedule"})
            continue
        cutoff = timestamp(market["scheduled_end_date"]) - int(lead_hours*3600)
        if cutoff < cohort_at:
            exclusions.append({"market_id": market["market_id"], "reason": "forecast_before_frozen_cohorts"})
            continue
        if cutoff >= label_at:
            exclusions.append({"market_id": market["market_id"], "reason": "market_already_resolved_at_scheduled_forecast"})
            continue
        if market["trading_start"] and timestamp(market["trading_start"]) > cutoff:
            exclusions.append({"market_id": market["market_id"], "reason": "market_not_open_at_forecast"})
            continue
        yes_token = next(r["token_id"] for r in read_table(folder / "outcomes.csv") if r["outcome"].lower() == "yes")
        reference = price_at(read_table(folder / "prices.csv.gz"), yes_token, cutoff, max_price_age_hours*3600)
        if reference is None:
            exclusions.append({"market_id": market["market_id"], "reason": "no_fully_available_recent_nonterminal_price"})
            continue
        if cutoff < test_start and label_at >= test_start:
            exclusions.append({"market_id": market["market_id"], "reason": "calibration_label_not_available_at_model_fit"})
            continue
        split = "calibration" if cutoff < test_start else "test"
        features = flow_features(read_table(folder / "trades.csv.gz"), cutoff, cohorts)
        forecasts.append({"market_id": market["market_id"], "economic_cluster_id": market["economic_cluster_id"],
                          "prediction_at": cutoff, "prediction_at_utc": iso(cutoff), "split": split,
                          "label_available_at": label_at, "yes_outcome": int(market["yes_outcome"]),
                          "market_probability": float(reference["price"]),
                          "price_available_at": int(reference["available_at"]),
                          "price_age_seconds": cutoff-int(reference["available_at"]), **features})
    calibration = [r for r in forecasts if r["split"] == "calibration"]
    test = [r for r in forecasts if r["split"] == "test"]
    # This invariant is checked before fitting; test labels never reach the fitter.
    if any(r["label_available_at"] >= test_start for r in calibration):
        raise ValueError("Future calibration label")
    fields = ["top_decile_flow", "bottom_decile_flow"]
    coefficients = fit(calibration, fields, penalty)
    all_coefficients = fit(calibration, ["all_wallet_flow"], penalty)
    for row in forecasts:
        row["cohort_probability"] = predict(row["market_probability"], [row[f] for f in fields], coefficients)
        row["all_wallet_probability"] = predict(row["market_probability"], [row["all_wallet_flow"]], all_coefficients)
    table(out / "forecasts.csv", forecasts, list(forecasts[0]) if forecasts else ["market_id"])
    table(out / "excluded_markets.csv", exclusions, ["market_id", "reason"])
    model = {"fit_cutoff": test_start, "fit_markets": len(calibration), "fields": fields,
             "coefficients": coefficients, "all_wallet_coefficient": all_coefficients,
             "penalty": penalty, "intercept": "not fitted; quoted price is the offset",
             "probability_model": "sigmoid(logit(market_probability) + coefficient dot flow)",
             "zero_signal": "exactly the quoted market probability"}
    dump(out / "model.json", model)
    weeks = {datetime.fromtimestamp(r["prediction_at"], timezone.utc).isocalendar()[:2] for r in test}
    summary = {"status": "exploratory retrospective backtest, not proof of wallet skill",
               "cohort_as_of": iso(cohort_at), "fit_as_of": iso(test_start),
               "wallets_per_decile": cohorts["decile_size"], "calibration_markets": len(calibration),
               "test_markets": len(test), "excluded_markets": len(exclusions),
               "test_market_baseline": score(test, "market_probability"),
               "test_all_wallet_model": score(test, "all_wallet_probability"),
               "test_top_bottom_model": score(test, "cohort_probability"),
               "test_markets_with_cohort_activity": sum(r["top_decile_active_wallets"]+r["bottom_decile_active_wallets"]>0 for r in test),
               "test_prediction_calendar_weeks": len(weeks),
               "confidence_interval": None,
               "uncertainty_reason": "pilot has few markets/time blocks; no robust confidence claim is made",
               "limitations": ["Schedules/rules are collection-time metadata, not historical schedule snapshots",
                               "Formal resolution can lag public outcome knowledge; public announcement timestamps not fully collected",
                               "Quoted benchmark is a sparse historical price, not a pre-trade order-book midpoint",
                               "Deciles are relative rankings, not statistically established skilled/unskilled groups",
                               "Complete wallet inventory/cost histories and individual wallet probability forecasts unavailable"]}
    dump(out / "summary.json", summary)
    manifest(out, [dataset / "manifest.json", wallet_output / "cohorts.json", wallet_output / "manifest.json",
                   Path(__file__), Path(__file__).with_name("wallet_metrics.py"), Path(__file__).with_name("artifacts.py")])
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--wallet-metrics", type=Path, default=WALLET_OUTPUT)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--test-start", type=timestamp, default=TEST_START)
    parser.add_argument("--lead-hours", type=float, default=24)
    parser.add_argument("--max-price-age-hours", type=float, default=24)
    parser.add_argument("--penalty", type=float, default=.1)
    args = parser.parse_args()
    if not all(math.isfinite(v) and v > 0 for v in (args.lead_hours,args.max_price_age_hours,args.penalty)):
        parser.error("Lead time, quote age limit and penalty must be finite and positive")
    build(args.dataset,args.wallet_metrics,args.out,args.test_start,args.lead_hours,args.max_price_age_hours,args.penalty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
