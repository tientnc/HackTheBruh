"""Collect retrospective position economics; expose an explicitly provisional return ratio."""

import argparse
import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .artifacts import manifest
from .client import Client, pages
from .dataset import dump, gzread, gzwrite, read_table, table
from .research import now
from .wallet_metrics import DATASET

OUTPUT = Path("datasets/finance/position-evidence-100-2025/v1")


def normalize(market, positions):
    """Merge token sides before computing a wallet-market return proxy.

    Snapshot state is usable only after its last economics event and final label.
    Neither current mark nor the API's percent_realized_pnl is a historical ROI.
    """
    unique = {}
    for row in positions:
        if row["condition_id"] != market["condition_id"]:
            raise ValueError("Wrong condition in positions feed")
        key = (row["proxy_wallet"].lower(), row["token_id"])
        if key in unique:
            fields = ("realized_pnl", "total_size", "avg_price", "last_event_at", "first_entry_at")
            if any(unique[key].get(k) != row.get(k) for k in fields):
                raise ValueError("Conflicting position snapshots across lifecycle pages")
        unique[key] = row
    grouped = defaultdict(list)
    for (wallet, _), row in unique.items():
        grouped[wallet].append(row)
    result = []
    for wallet, rows in sorted(grouped.items()):
        values = [r.get(k) for r in rows for k in ("realized_pnl", "total_size", "avg_price")]
        valid = all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
        clocks = all(int(r.get("last_event_at") or 0) > 0 and int(r.get("first_entry_at") or 0) > 0
                     and int(r["first_entry_at"]) <= int(r["last_event_at"]) for r in rows)
        basis = sum(r["total_size"] * r["avg_price"] for r in rows) if valid else None
        pnl = sum(r["realized_pnl"] for r in rows) if valid else None
        valid = valid and clocks and all(r["total_size"] >= 0 and 0 <= r["avg_price"] <= 1 for r in rows) and basis > 1e-6
        result.append({"wallet": wallet, "market_id": market["market_id"],
                       "economic_cluster_id": market["economic_cluster_id"], "category": market["subfield"],
                       "available_at": max(int(market["label_available_at"]), max(int(r.get("last_event_at") or 0) for r in rows)),
                       "position_tokens": len(rows), "reported_realized_pnl_usdc": pnl,
                       "estimated_cumulative_entry_basis_usdc": basis,
                       "reported_return_proxy": pnl/basis if valid else None,
                       "usable_return_proxy": valid,
                       "accounting": "provider realized PnL / sum(lifetime bought shares * WAC price); not reconciled after-cost ROI"})
    return result


def build(dataset, out, workers=3, max_pages=100):
    out.mkdir(parents=True, exist_ok=True)
    settings = {"dataset": dataset.as_posix(), "status": ["CLOSED", "OPEN"], "page_limit": 1000,
                "max_pages": max_pages, "open_include_archived": True,
                "return_definition": "reported realized PnL / estimated cumulative acquisition basis; provisional"}
    if (out / "config.json").exists() and json.loads((out / "config.json").read_text()) != settings:
        raise ValueError("Different settings; choose a new output path")
    dump(out / "config.json", settings)

    def collect(market):
        raw_path = out / "raw" / (market["market_id"] + ".json.gz")
        if raw_path.exists():
            raw = gzread(raw_path)
        else:
            raw = {"market_id": market["market_id"], "condition_id": market["condition_id"], "collected_at": now(), "feeds": {}}
            for status in ("CLOSED", "OPEN"):
                params = {"condition": market["condition_id"], "status": status, "limit": 1000}
                if status == "OPEN":
                    params["include_archived"] = True
                rows, responses, exhausted = pages(Client(), "/v2/positions", params, max_pages)
                if not exhausted:
                    raise ValueError("Position pagination incomplete")
                raw["feeds"][status] = {"params": params, "pages": responses}
            gzwrite(raw_path, raw)
        positions = [r for feed in raw["feeds"].values() for page in feed["pages"] for r in page["data"]]
        return normalize(market, positions)

    rows, errors, completed = [], [], 0
    markets = read_table(dataset / "markets.csv")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collect, m): m for m in markets}
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
                completed += 1
            except Exception as error:
                errors.append({"market_id": futures[future]["market_id"], "error": str(error)})
            if (completed+len(errors)) % 10 == 0:
                print(f"Position evidence: {completed} complete, {len(errors)} errors", flush=True)
    rows.sort(key=lambda r: (r["market_id"], r["wallet"]))
    table(out / "wallet_market_returns.csv.gz", rows, list(rows[0]) if rows else ["wallet"])
    dump(out / "errors.json", errors)
    summary = {"source_markets": len(markets), "completed_markets": completed, "errors": len(errors),
               "wallet_market_rows": len(rows), "usable_return_rows": sum(r["usable_return_proxy"] for r in rows),
               "wallets": len({r["wallet"] for r in rows}),
               "status": "retrospective provider return proxies, not audited ROI or proof of skill"}
    dump(out / "summary.json", summary)
    manifest(out, [dataset / "manifest.json", dataset / "markets.csv", Path(__file__), Path(__file__).with_name("artifacts.py")])
    print(json.dumps(summary, indent=2))
    if errors:
        raise ValueError("Position collection incomplete; inspect errors.json and resume")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    build(args.dataset, args.out, args.workers)


if __name__ == "__main__":
    main()
