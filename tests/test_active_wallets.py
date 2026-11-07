import tempfile
import unittest
from pathlib import Path

from polyresearch.active_wallets import rank_wallets
from polyresearch.dataset import table


class ActiveWalletTests(unittest.TestCase):
    def test_market_breadth_and_trade_count_are_distinct_past_only_rankings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            markets = [{"folder": "one", "economic_cluster_id": "one", "label_available_at": 90},
                       {"folder": "two", "economic_cluster_id": "two", "label_available_at": 95},
                       {"folder": "future", "economic_cluster_id": "future", "label_available_at": 100}]
            table(root / "markets.csv", markets, list(markets[0]))
            def row(wallet, at=50):
                return {"wallet": wallet, "timestamp": at, "notional_usdc": 10}
            one = [row("a"), row("b"), row("b"), row("b"), row("c", 90)]
            two = [row("a")]
            for name, rows, takers in [("one", one, [row("b")]), ("two", two, [])]:
                table(root / name / "wallet_trade_legs.csv.gz", rows, list(rows[0]))
                table(root / name / "trades.csv.gz", takers, list(rows[0]))
            rows, count = rank_wallets(root, 100)
            self.assertEqual(count, 2)
            self.assertEqual([r["wallet"] for r in rows], ["a", "b"])
            self.assertEqual(rows[0]["resolved_markets"], 2)
            self.assertEqual(rows[0]["trade_leg_rows"], 2)
            self.assertEqual(rows[1]["taker_trade_rows"], 1)
            self.assertEqual(rows[1]["trade_leg_rows"], 3)
            self.assertEqual(rows[1]["notional_usdc"], 30)
            self.assertEqual(rank_wallets(root, 100, "trade-legs")[0][0]["wallet"], "b")


if __name__ == "__main__":
    unittest.main()
