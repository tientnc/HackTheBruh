"""Export a small, genuine-data preview for the Vercel demo. No full trade archive."""

import json
from pathlib import Path

from .artifacts import sha256
from .cloud import EXPERIMENT, EXPERIMENT_KEY, SOURCES, number
from .dataset import dump, read_table
from .research import timestamp


def export(out=Path("web/public/data/snapshot.json")):
    datasets, markets = [], []
    for key,title,phase,root in SOURCES:
        manifest=json.loads((root/"manifest.json").read_text())
        datasets.append({"dataset_key":key,"title":title,"phase":phase,"status":"ready",
                         "market_count":manifest["counts"]["markets_selected"],
                         "trade_leg_count":manifest["counts"]["wallet_activity_rows"],
                         "taker_count":manifest["counts"]["taker_trade_rows"],"price_count":manifest["counts"]["price_points"]})
        for row in read_table(root/"markets.csv"):
            meta=json.loads((root/row["folder"]/"market.json").read_text())
            markets.append({"dataset_key":key,"market_id":row["market_id"],"question":row["question"],
                            "category":row["subfield"],"source_url":meta["source_url"],
                            "label_available_at":int(row["label_available_at"]),"yes_outcome":int(row["yes_outcome"]),
                            "trading_start":timestamp(row["trading_start"]),
                            "scheduled_end":timestamp(row["scheduled_end_date"]) if row["scheduled_end_date"] else None})
    predictions=[]
    for row in read_table(EXPERIMENT/"predictions.csv"):
        predictions.append({"experiment_key":EXPERIMENT_KEY,"market_id":row["market_id"],
                            "forecast_at":int(row["forecast_at"]),"window_end":int(row["window_end"]),
                            "group_name":row["group"],"side":row["side"],"group_size":int(row["group_size"]),
                            "actual_wallets":int(row["actual_wallets"]),"predicted_wallets":float(row["model_predicted_wallets"]),
                            "historical_rate_wallets":float(row["historical_rate_predicted_wallets"]),"recent_wallets":int(row["recent_wallets"])})
    candidates=[]
    for row in read_table(EXPERIMENT/"candidate_wallets.csv"):
        candidates.append({"experiment_key":EXPERIMENT_KEY,"wallet":row["wallet"],"group_name":row["group"],
                           "activity_rank":int(row["rank"]),"resolved_markets":int(row["resolved_markets"]),
                           "earlier_comparable_markets":int(row["earlier_comparable_markets"]),
                           "fraction_above_winner_mean":number(row.get("fraction_above_winner_mean")),
                           "mean_reported_return_proxy":number(row.get("mean_reported_return_proxy"))})
    result={"datasets":datasets,"markets":markets,"predictions":predictions,"candidates":candidates,
            "experiment":{"experiment_key":EXPERIMENT_KEY,"summary":json.loads((EXPERIMENT/"summary.json").read_text()),
                          "source_sha256":sha256(EXPERIMENT/"manifest.json")},
            "snapshot_notice":"Published historical results. This preview does not connect to Supabase unless configured."}
    dump(out,result)
    print(f"Preview exported: {out} ({out.stat().st_size:,} bytes)")
    return result


if __name__ == "__main__":
    export()
