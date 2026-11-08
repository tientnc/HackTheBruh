#!/usr/bin/env python3
"""Fetch finance wallet classifications from the API and save them as CSV."""

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

OUTPUT_FILE = Path(__file__).with_name("tiers.csv")
DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 600


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc}") from exc


def export_tiers(
    api_url: str,
    output_file: Path = OUTPUT_FILE,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    base_url = api_url.rstrip("/")
    wallets = fetch_json(f"{base_url}/wallets/finance", timeout)
    results = fetch_json(f"{base_url}/wallets/finance/results", timeout)

    if not isinstance(wallets, list):
        raise ValueError("GET /wallets/finance must return a JSON list")
    if not isinstance(results, dict):
        raise ValueError("GET /wallets/finance/results must return a JSON object")

    rows = []
    for entry in wallets:
        if not isinstance(entry, dict) or not isinstance(entry.get("wallet_id"), str):
            raise ValueError("Each finance wallet must include a wallet_id string")
        wallet = entry["wallet_id"]
        if wallet not in results:
            raise ValueError(f"No classification returned for wallet {wallet}")
        tier = results[wallet]
        if not isinstance(tier, str):
            raise ValueError(f"Classification for wallet {wallet} must be a string")
        rows.append((wallet, tier))
        print(f"{wallet},{tier}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(("wallet", "tier"))
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.getenv("API_BASE_URL", DEFAULT_API_URL),
        help="API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout in seconds for each API request (default: %(default)s)"
    )
    args = parser.parse_args()
    # export_tiers(args.api_url, timeout=args.timeout)
    count = export_tiers(args.api_url, timeout=args.timeout)
    print(f"Wrote {count} wallet tiers to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
