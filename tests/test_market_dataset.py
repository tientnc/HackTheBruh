import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyresearch.market_dataset import (MARKET_URL, build, normalize_trades, resolve,
                                        resume_trade_cache, summarize_wallets, url_parts, validate)
from polyresearch.research import timestamp


class MarketDatasetTests(unittest.TestCase):
    def test_exact_market_url_required(self):
        event, market = url_parts(MARKET_URL)
        self.assertEqual(event, "anthropic-ipo-closing-market-cap-higher-strikes")
        self.assertTrue(market.startswith("will-anthropics-market-cap"))
        for bad in ("https://other.example/event/a/b", "https://polymarket.com/event/a"):
            with self.assertRaises(ValueError):
                url_parts(bad)

    def test_wrong_event_is_rejected(self):
        class FakeClient:
            def get(self, *args, **kwargs):
                return [{"slug": url_parts(MARKET_URL)[1], "conditionId": "condition",
                         "events": [{"slug": "wrong-event"}]}]
        with self.assertRaisesRegex(Exception, "does not belong"):
            resolve(FakeClient(), MARKET_URL)

    def test_wallet_rollup_accepts_csv_strings(self):
        rows = [{"wallet": "alice", "timestamp": "10", "side": "BUY", "outcome": "Yes", "notional_usdc": "4.5"},
                {"wallet": "alice", "timestamp": "20", "side": "SELL", "outcome": "No", "notional_usdc": "2"}]
        result = summarize_wallets(rows, rows[:1])[0]
        self.assertEqual(result["yes_signed_flow_usdc"], 6.5)
        self.assertEqual(result["market_trade_leg_rows"], 2)
        self.assertEqual(result["taker_trade_rows"], 1)
        self.assertEqual((result["first_seen"], result["last_seen"]), (10, 20))

    def test_resume_incomplete_trade_feed_keeps_cursor_filters_and_window(self):
        cached={"raw_pages":[{"pagination":{"next_cursor":"resume-here"}}],"trades":[{"timestamp":50}],
                "pagination_exhausted":False,"rows_scanned":1,"earliest_scanned":50,"latest_scanned":50}
        next_page={"pagination":{"next_cursor":None,"has_more":False}}
        with patch("polyresearch.market_dataset.pages",return_value=([{"timestamp":40},{"timestamp":1}],[next_page],True)) as walk:
            result=resume_trade_cache(cached,"wallet_trade_legs","condition",10,100,3)
        self.assertEqual(walk.call_args.args[2],{"condition":"condition","taker_only":False,"limit":1000,"cursor":"resume-here"})
        self.assertEqual(walk.call_args.args[3],2)
        self.assertEqual(result["trades"],[{"timestamp":50},{"timestamp":40}])
        self.assertTrue(result["pagination_exhausted"])
        self.assertEqual(result["earliest_scanned"],1)
        self.assertEqual(result["rows_scanned"],3)

    def test_complete_build_validates_and_detects_tampering(self):
        event_slug, market_slug = url_parts(MARKET_URL)
        condition = "0x" + "c" * 64
        market = {"id": "1", "conditionId": condition, "slug": market_slug,
                  "question": "Anthropic IPO bracket?", "createdAt": "2026-06-01T18:00:00Z",
                  "startDate": "2026-06-01T21:00:00Z", "endDate": "2028-01-01T00:00:00Z",
                  "outcomes": '["Yes","No"]', "clobTokenIds": '["token-yes","token-no"]',
                  "events": [{"id": "2", "slug": event_slug}]}
        t = timestamp("2026-06-02")
        buy = {"condition_id": condition, "timestamp": t, "proxy_wallet": "0x" + "a" * 40,
               "side": "BUY", "outcome": "Yes", "token_id": "token-yes", "size": 10,
               "price": .3, "transaction_hash": "hash"}
        sell = {**buy, "proxy_wallet": "0x" + "b" * 40, "side": "SELL"}
        trade_data = {"trades": [buy], "pagination_exhausted": True}

        def prices(client, token, *args):
            return {"points": [{"timestamp": t, "price": .3 if token == "token-yes" else .7,
                                 "resolution_seconds": 10800}], "pagination_exhausted": True}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("polyresearch.market_dataset.resolve", return_value=market), \
                 patch("polyresearch.market_dataset.collect_trades", return_value=trade_data), \
                 patch("polyresearch.market_dataset.collect_prices", side_effect=prices), \
                 patch("polyresearch.market_dataset.pages", return_value=([buy, sell], [], True)):
                manifest = build(root)
            self.assertEqual(manifest["counts"]["taker_trade_rows"], 1)
            self.assertEqual(manifest["counts"]["wallet_trade_leg_rows"], 2)
            self.assertTrue(validate(root)["passed"])
            with (root / "wallets.csv").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            result = validate(root)
            self.assertFalse(result["passed"])
            self.assertIn("Checksum mismatch: wallets.csv", result["issues"])


if __name__ == "__main__":
    unittest.main()
