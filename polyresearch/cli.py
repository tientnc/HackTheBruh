import argparse
import json
import sys
from pathlib import Path

from .client import ApiError, Client
from .research import (classify, cohorts, collect_prices, collect_trades, discover,
                       timestamp, wallet_snapshot)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each output is a research artifact; accidental reruns must not replace evidence.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parser():
    root = argparse.ArgumentParser(description="Polymarket finance research (read-only public APIs)")
    commands = root.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser("discover", help="Find finance markets, including historical ones")
    discovery.add_argument("--start", type=timestamp)
    discovery.add_argument("--end", type=timestamp)
    discovery.add_argument("--status", choices=["all", "open", "closed"], default="all")
    discovery.add_argument("--max-events", type=positive, default=100)
    discovery.add_argument("--out", default="data/finance-markets.json")

    collect = commands.add_parser("collect", help="Collect one discovered market's trades and prices")
    collect.add_argument("--markets", default="data/finance-markets.json")
    collect.add_argument("--slug", required=True)
    collect.add_argument("--start", type=timestamp, required=True)
    collect.add_argument("--end", type=timestamp, required=True, help="Exclusive UTC boundary")
    collect.add_argument("--max-pages", type=positive, default=20)
    collect.add_argument("--bucket-seconds", type=positive, default=10800)
    collect.add_argument("--out", required=True, help="New output directory")

    wallets = commands.add_parser("wallets", help="Create pre-window baseline snapshots for sampled takers")
    wallets.add_argument("--trades", required=True)
    wallets.add_argument("--as-of", type=timestamp, required=True, help="Exclusive cutoff, no later than flow start")
    wallets.add_argument("--max-wallets", type=positive, default=10)
    wallets.add_argument("--max-pages", type=positive, default=20)
    wallets.add_argument("--out", required=True)
    report = commands.add_parser("cohorts", help="Compute the four groups, plus unknown/neutral")
    report.add_argument("--trades", required=True)
    report.add_argument("--snapshots", required=True)
    report.add_argument("--wallet-cap", type=float, default=1000)
    report.add_argument("--out", required=True)
    for command in (wallets, report):
        command.add_argument("--min-trades", type=positive, default=100)
        command.add_argument("--min-profit", type=float, default=0)
    return root


def run(args, client):
    if args.command in ("discover", "collect"):
        if args.start is not None and args.end is not None and args.start >= args.end:
            raise ValueError("--start must be before --end")
    if args.command != "collect" and Path(args.out).exists():
        raise FileExistsError(f"Output already exists: {args.out}. Choose a new path.")
    if args.command == "discover":
        result = discover(client, args.start, args.end, args.max_events, args.status)
        write(args.out, result)
        print(f"Saved {len(result['markets'])} markets from {result['events_scanned']} events to {args.out}")
        if not result["discovery_exhausted"]:
            print("Discovery stopped at --max-events; the market universe is incomplete.")
        for market in result["markets"][:12]:
            print(f"  {market['slug']}: {market['question']}")
    elif args.command == "collect":
        candidates = [m for m in read(args.markets)["markets"] if m["slug"] == args.slug]
        if len(candidates) != 1:
            raise ValueError("--slug must identify exactly one market in --markets")
        market = candidates[0]
        output = Path(args.out)
        output.mkdir(parents=True, exist_ok=False)
        write(output / "market.json", market)
        # Persist trades before requesting prices, so price failures do not erase them.
        trades = collect_trades(client, market["condition_id"], args.start, args.end, args.max_pages)
        write(output / "trades.json", trades)
        print(f"Saved {len(trades['trades'])} window trades; feed exhausted: {trades['pagination_exhausted']}")
        price_files = []
        for i, outcome in enumerate(market["outcomes"]):
            if not outcome["token_id"]:
                print(f"No CLOB token for {outcome['label']}; price history unavailable.")
                continue
            prices = collect_prices(client, outcome["token_id"], args.start, args.end,
                                    args.bucket_seconds, args.max_pages)
            filename = f"prices-{i}.json"
            write(output / filename, prices)
            price_files.append(filename)
            print(f"Saved {len(prices['points'])} price points for {outcome['label']}")
        write(output / "manifest.json", {"market": "market.json", "trades": "trades.json",
                                         "prices": price_files, "collection_finished": True})
    elif args.command == "wallets":
        trades = read(args.trades)
        if args.as_of > trades["start"]:
            raise ValueError("--as-of must be at or before the trade window start")
        addresses = sorted({r["proxy_wallet"].lower() for r in trades["trades"] if r.get("proxy_wallet")})
        snapshots = []
        for wallet in addresses[:args.max_wallets]:
            print(f"Inspecting {wallet}", flush=True)
            try:
                snapshot = wallet_snapshot(client, wallet, args.as_of, args.max_pages,
                                           args.min_trades, args.min_profit)
            except ApiError as error:
                snapshot = {"wallet": wallet, "as_of": args.as_of, "label": "unknown",
                            "history_exhausted": False, "error": str(error)}
                print(f"  Unavailable: {error}", file=sys.stderr)
            snapshots.append(snapshot)
        write(args.out, {"as_of": args.as_of, "wallets_in_trade_sample": len(addresses),
                         "wallets_requested": min(len(addresses), args.max_wallets),
                         "sampling": "lexicographic address order; remaining wallets are unknown",
                         "snapshots": snapshots})
        print(f"Saved {len(snapshots)} snapshots to {args.out}")
    elif args.command == "cohorts":
        result = cohorts(read(args.trades), read(args.snapshots)["snapshots"],
                         args.wallet_cap, args.min_trades, args.min_profit)
        write(args.out, result)
        print(json.dumps({k: v for k, v in result.items() if k != "meaning"}, indent=2))


def main():
    args = parser().parse_args()
    try:
        run(args, Client())
    except (ApiError, ValueError, OSError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0
