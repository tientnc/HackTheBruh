"""Prepare or import the public research snapshots into Supabase.

Default is an offline plan/export. --apply needs a migrated project and an
import-only service key in the environment. Browser code never receives that key.
"""

import argparse
import base64
import csv
import gzip
import hashlib
import json
import mimetypes
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .artifacts import sha256, verify
from .dataset import dump, read_table
from .research import timestamp
from .resolved_dataset import validate

SOURCES = [("finance-2025-v1", "2025 · earlier markets", "earlier", Path("datasets/finance/resolved-100-2025/v1")),
           ("finance-2026-01-v1", "January 2026 · later markets", "later", Path("datasets/finance/resolved-20-2026-01/v1"))]
EXPERIMENT = Path("analysis/participation/2026-01/v1")
RETURNS = Path("datasets/finance/position-evidence-100-2025/v1")
EXPERIMENT_KEY = "participation-2026-01-v1"
BUCKET = "hackthebruh-research"


def rows(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def number(value, kind=float):
    return kind(value) if value not in (None, "") else None


def trade_key(row):
    return tuple(row[k] for k in ("timestamp", "wallet", "side", "outcome", "token_id", "size_shares", "price", "transaction_hash"))


def normalized_trades(root, market):
    folder = root / market["folder"]
    takers = Counter(trade_key(r) for r in rows(folder / "trades.csv.gz"))
    for index, row in enumerate(rows(folder / "wallet_trade_legs.csv.gz"), 1):
        key = trade_key(row)
        is_taker = takers[key] > 0
        if is_taker:
            takers[key] -= 1
        yield {"market_id": market["market_id"], "source_row": index, "observed_at": int(row["timestamp"]),
               "wallet": row["wallet"], "side": row["side"], "outcome": row["outcome"],
               "size_shares": float(row["size_shares"]), "price": float(row["price"]), "is_taker": is_taker}
    if any(takers.values()):
        raise ValueError(f"Taker rows missing from all-side feed: {market['market_id']}")


def artifacts():
    for base in (Path("datasets"), Path("analysis")):
        for path in sorted(base.rglob("*")):
            if path.is_file():
                digest = sha256(path)
                content_type = "application/gzip" if path.suffix == ".gz" else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                yield {"source_path": path.as_posix(), "object_path": f"sha256/{digest}/{path.as_posix()}",
                       "sha256": digest, "bytes": path.stat().st_size, "content_type": content_type}


def prepare(out=Path("data/cloud-export"), check_sources=True):
    out.mkdir(parents=True, exist_ok=True)
    if check_sources:
        for _, _, _, root in SOURCES:
            result = validate(root)
            if not result["passed"]:
                raise ValueError(f"Source snapshot failed validation: {root}")
        verify(EXPERIMENT)
        verify(RETURNS)
    counts = Counter()
    handles = {}
    def emit(table_name, row):
        if table_name not in handles:
            handles[table_name] = (out / f"{table_name}.jsonl").open("w", encoding="utf-8", newline="\n")
        handles[table_name].write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        counts[table_name] += 1
    wallets = set()
    try:
        for dataset_key, title, phase, root in SOURCES:
            source = json.loads((root / "manifest.json").read_text())
            totals = source["counts"]
            emit("research_datasets", {"dataset_key": dataset_key, "title": title, "phase": phase,
                "source_path": root.as_posix(), "source_sha256": sha256(root / "manifest.json"),
                "market_count": totals["markets_selected"], "trade_leg_count": totals["wallet_activity_rows"],
                "taker_count": totals["taker_trade_rows"], "price_count": totals["price_points"], "status": "loading"})
            for market in read_table(root / "markets.csv"):
                folder = root / market["folder"]
                tokens = {r["outcome"].lower(): r["token_id"] for r in read_table(folder / "outcomes.csv")}
                meta = json.loads((folder / "market.json").read_text())
                emit("research_markets", {"dataset_key": dataset_key, "market_id": market["market_id"],
                    "condition_id": market["condition_id"], "event_id": market["event_id"],
                    "economic_cluster_id": market["economic_cluster_id"], "question": market["question"],
                    "category": market["subfield"], "trading_start": timestamp(market["trading_start"]) if market["trading_start"] else None,
                    "scheduled_end": timestamp(market["scheduled_end_date"]) if market["scheduled_end_date"] else None,
                    "label_available_at": int(market["label_available_at"]), "yes_outcome": int(market["yes_outcome"]),
                    "yes_token_id": tokens["yes"], "no_token_id": tokens["no"], "source_url": meta["source_url"]})
                for row in normalized_trades(root, market):
                    wallets.add(row["wallet"])
                    emit("research_trades", {"dataset_key": dataset_key, **row})
                for index, row in enumerate(rows(folder / "prices.csv.gz"), 1):
                    emit("research_prices", {"dataset_key": dataset_key, "market_id": market["market_id"], "source_row": index,
                        "outcome": row["outcome"], "observed_at": int(row["timestamp"]), "available_at": int(row["available_at"]),
                        "resolution_seconds": int(row["resolution_seconds"]), "price": float(row["price"])})
        for row in rows(RETURNS / "wallet_market_returns.csv.gz"):
            wallets.add(row["wallet"])
            emit("research_returns", {"wallet": row["wallet"], "market_id": row["market_id"],
                "economic_cluster_id": row["economic_cluster_id"], "category": row["category"], "available_at": int(row["available_at"]),
                "reported_realized_pnl_usdc": number(row["reported_realized_pnl_usdc"]),
                "estimated_entry_basis_usdc": number(row["estimated_cumulative_entry_basis_usdc"]),
                "reported_return_proxy": number(row["reported_return_proxy"]), "usable": row["usable_return_proxy"] == "True"})
        summary = json.loads((EXPERIMENT / "summary.json").read_text())
        config = json.loads((EXPERIMENT / "config.json").read_text())
        emit("research_experiments", {"experiment_key": EXPERIMENT_KEY, "title": "Next-week participation · January 2026",
            "fit_at": config["fit_at"], "horizon_days": config["horizon_days"], "summary": summary,
            "source_sha256": sha256(EXPERIMENT / "manifest.json"), "status": "loading"})
        for row in rows(EXPERIMENT / "candidate_wallets.csv"):
            wallets.add(row["wallet"])
            emit("research_candidates", {"experiment_key": EXPERIMENT_KEY, "wallet": row["wallet"], "group_name": row["group"],
                "activity_rank": int(row["rank"]), "resolved_markets": int(row["resolved_markets"]),
                "earlier_comparable_markets": int(row["earlier_comparable_markets"]),
                "fraction_above_winner_mean": number(row.get("fraction_above_winner_mean")),
                "mean_reported_return_proxy": number(row.get("mean_reported_return_proxy"))})
        for row in rows(EXPERIMENT / "predictions.csv"):
            emit("research_predictions", {"experiment_key": EXPERIMENT_KEY, "market_id": row["market_id"],
                "forecast_at": int(row["forecast_at"]), "window_end": int(row["window_end"]), "group_name": row["group"],
                "side": row["side"], "group_size": int(row["group_size"]), "actual_wallets": int(row["actual_wallets"]),
                "predicted_wallets": float(row["model_predicted_wallets"]), "historical_rate_wallets": float(row["historical_rate_predicted_wallets"]),
                "recent_wallets": int(row["recent_wallets"])})
        for address in sorted(wallets):
            emit("research_wallets", {"address": address})
        artifact_rows = list(artifacts())
        for row in artifact_rows:
            emit("research_artifacts", row)
    finally:
        for handle in handles.values():
            handle.close()
    plan = {"tables": dict(counts), "artifact_files": len(artifact_rows), "artifact_bytes": sum(r["bytes"] for r in artifact_rows),
            "largest_artifact_bytes": max(r["bytes"] for r in artifact_rows),
            "jsonl_bytes": sum(p.stat().st_size for p in out.glob("research_*.jsonl")),
            "storage_bucket": BUCKET, "raw_file_quota_bytes": 1_000_000_000, "database_quota_bytes": 500_000_000,
            "note": "JSON export size is not PostgreSQL disk size. Measure tables and indexes after import."}
    if plan["largest_artifact_bytes"] > 50_000_000:
        raise ValueError("A file exceeds the Free-plan upload limit")
    if plan["artifact_bytes"] > plan["raw_file_quota_bytes"]:
        raise ValueError("Files exceed the Free-plan storage allowance")
    dump(out / "plan.json", plan)
    return plan


class Supabase:
    def __init__(self, url, key):
        if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", url):
            raise ValueError("Expected HTTPS Supabase project URL")
        if not key or key.startswith("sb_publishable_"):
            raise ValueError("Import requires a server-only service key")
        if key.count(".") == 2:
            try:
                segment=key.split(".")[1]
                payload=json.loads(base64.urlsafe_b64decode(segment+"="*(-len(segment)%4)))
            except Exception:
                raise ValueError("Invalid legacy service key") from None
            if payload.get("role") != "service_role":
                raise ValueError("Import requires service_role, not an anonymous browser key")
        self.url, self.key = url, key

    def request(self, method, path, body=None, content_type="application/json", headers=None, headers_only=False):
        request_headers = {"apikey": self.key, "Content-Type": content_type, **(headers or {})}
        if self.key.count(".") == 2:
            request_headers["Authorization"] = "Bearer " + self.key
        data = json.dumps(body, allow_nan=False).encode() if body is not None and not isinstance(body, bytes) else body
        for attempt in range(4):
            try:
                with urlopen(Request(self.url+path, data=data, method=method, headers=request_headers), timeout=90) as response:
                    if headers_only:
                        return dict(response.headers)
                    payload = response.read()
                    return json.loads(payload) if payload else None
            except HTTPError as error:
                detail = error.read(1000).decode(errors="replace").replace(self.key,"[redacted]")
                if error.code in (429, 500, 502, 503, 504) and attempt < 3:
                    try:
                        delay=float(error.headers.get("Retry-After",2**attempt))
                    except (TypeError,ValueError):
                        delay=2**attempt
                    if delay>30:
                        raise RuntimeError("Supabase requests a longer retry pause; resume the import later") from None
                    time.sleep(max(0,delay))
                    continue
                raise RuntimeError(f"Supabase {method} failed ({error.code}): {detail}") from None
            except URLError:
                if attempt == 3:
                    raise RuntimeError("Could not reach Supabase") from None
                time.sleep(2**attempt)

    def upsert(self, table_name, data):
        return self.request("POST", "/rest/v1/"+table_name, data,
                            headers={"Prefer":"resolution=merge-duplicates,return=minimal"})

    def count(self, table_name):
        headers=self.request("HEAD","/rest/v1/"+table_name+"?select=*",headers={"Prefer":"count=exact"},headers_only=True)
        value=next((v for k,v in headers.items() if k.lower()=="content-range"),"")
        if not value or value.rsplit("/",1)[-1]=="*":
            raise ValueError("Supabase did not return an exact row count")
        return int(value.rsplit("/",1)[-1])


def apply(export, client, workers=4, batch_size=1000):
    plan = json.loads((export / "plan.json").read_text())
    already_ready=set()
    # All schema/immutability checks precede uploads and writes.
    for table_name, field in (("research_datasets","dataset_key"),("research_experiments","experiment_key")):
        for line in (export / f"{table_name}.jsonl").read_text().splitlines():
            row = json.loads(line)
            prior = client.request("GET", "/rest/v1/"+table_name+"?"+urlencode({field:"eq."+row[field],"select":"source_sha256,status"}))
            if prior and prior[0]["source_sha256"] != row["source_sha256"]:
                raise ValueError("Cloud snapshot differs from local version; choose a new version instead of replacing it")
            if prior and prior[0]["status"]=="ready":
                already_ready.add((table_name,row[field]))
    try:
        client.request("POST", "/storage/v1/bucket", {"id": BUCKET,"name":BUCKET,"public":True,"file_size_limit":50_000_000})
    except RuntimeError as error:
        if "already exists" not in str(error).lower() and "duplicate" not in str(error).lower():
            raise
        bucket = client.request("GET", "/storage/v1/bucket/"+BUCKET)
        if bucket.get("public") is not True:
            raise ValueError("Existing bucket is private; use a dedicated public-research bucket")
    artifact_rows = [json.loads(line) for line in (export / "research_artifacts.jsonl").read_text().splitlines()]
    def upload(row):
        path = Path(row["source_path"])
        if sha256(path) != row["sha256"]:
            raise ValueError("Source changed after export: " + str(path))
        try:
            client.request("POST", "/storage/v1/object/"+BUCKET+"/"+quote(row["object_path"], safe="/"),
                           path.read_bytes(), row["content_type"], {"x-upsert":"false","cache-control":"31536000"})
        except RuntimeError as error:
            if "duplicate" not in str(error).lower() and "already exists" not in str(error).lower():
                raise
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, _ in enumerate(pool.map(upload, artifact_rows), 1):
            if index % 100 == 0:
                print(f"Stored artifacts: {index}/{len(artifact_rows)}", flush=True)
    order = ("research_datasets","research_wallets","research_markets","research_trades","research_prices",
             "research_returns","research_experiments","research_candidates","research_predictions","research_artifacts")
    for name in order:
        batch = []
        sent = 0
        with (export / f"{name}.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                row=json.loads(line)
                field="dataset_key" if name=="research_datasets" else "experiment_key"
                if (name,row.get(field)) in already_ready:
                    row["status"]="ready"
                batch.append(row)
                if len(batch) >= batch_size:
                    client.upsert(name,batch)
                    sent += len(batch)
                    batch=[]
            if batch:
                client.upsert(name,batch)
                sent += len(batch)
        print(f"Imported {name}: {sent}",flush=True)
    # Mark complete only after server counts match the offline plan.
    for table_name in order:
        total = client.count(table_name)
        if total != plan["tables"][table_name]:
            raise ValueError(f"Server row count mismatch for {table_name}; import remains unpublished")
    for dataset_key,_,_,_ in SOURCES:
        client.request("PATCH","/rest/v1/research_datasets?dataset_key=eq."+dataset_key,{"status":"ready"})
    client.request("PATCH","/rest/v1/research_experiments?experiment_key=eq."+EXPERIMENT_KEY,{"status":"ready"})
    print("Import complete and verified. Anonymous access remains read-only.",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=Path("data/cloud-export"))
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    plan=prepare(args.out)
    print(json.dumps(plan,indent=2),flush=True)
    if args.apply:
        apply(args.out,Supabase(os.environ.get("SUPABASE_URL",""),os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")))


if __name__ == "__main__":
    main()
