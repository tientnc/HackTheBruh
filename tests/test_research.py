import unittest

from polyresearch.client import ApiError, pages
from polyresearch.research import (classify, cohorts, collect_prices, collect_trades,
                                  discover, timestamp, wallet_snapshot)


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, base, path, **params):
        self.calls.append((path, params))
        return next(self.responses)


def page(rows, cursor=None):
    return {"data": rows, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}}


def trade(wallet="alice", outcome="Yes", side="BUY", size=10, price=.5, t=110):
    return {"proxy_wallet": wallet, "condition_id": "condition", "outcome": outcome,
            "side": side, "size": size, "price": price, "timestamp": t}


class ResearchTests(unittest.TestCase):
    def test_cursor_keeps_filters_and_identical_legitimate_fills(self):
        row = trade()
        client = FakeClient([page([row], "next"), page([row])])
        rows, _, exhausted = pages(client, "/v2/trades", {"condition": "condition"})
        self.assertEqual(len(rows), 2)
        self.assertTrue(exhausted)
        self.assertEqual(client.calls[1][1], {"condition": "condition", "cursor": "next"})

    def test_bounded_pages_do_not_claim_complete(self):
        client = FakeClient([page([trade()], "more")])
        self.assertFalse(pages(client, "/v2/trades", {}, max_pages=1)[2])

    def test_repeated_cursor_fails(self):
        client = FakeClient([page([], "same"), page([], "same")])
        with self.assertRaises(ApiError):
            pages(client, "/v2/trades", {})

    def test_trade_window_filters_locally_and_is_end_exclusive(self):
        client = FakeClient([page([trade(t=t) for t in [99, 100, 199, 200]])])
        result = collect_trades(client, "condition", 100, 200)
        self.assertEqual([r["timestamp"] for r in result["trades"]], [100, 199])
        self.assertNotIn("start", client.calls[0][1])
        self.assertNotIn("end", client.calls[0][1])

    def test_wallet_uses_only_past_profit_and_preserves_missing_profit(self):
        points = [{"timestamp": 99, "realized_market_pnl": 5, "realized_combo_pnl": 2},
                  {"timestamp": 100, "realized_market_pnl": 1000, "realized_combo_pnl": 2}]
        client = FakeClient([page([trade(t=99)]), {"data": {"points": points}}])
        result = wallet_snapshot(client, "Alice", 100, min_trades=1)
        self.assertEqual(result["realized_trading_profit"], 7)
        self.assertEqual(result["pnl_observed_at"], 99)
        self.assertEqual(result["label"], "skilled")
        self.assertEqual(client.calls[0][1]["end"], 99)
        client = FakeClient([page([trade(t=99)]), {"data": {"points": [points[1]]}}])
        result = wallet_snapshot(client, "alice", 100, min_trades=1)
        self.assertIsNone(result["realized_trading_profit"])
        self.assertEqual(result["label"], "unknown")

    def test_zero_profit_and_truncated_history_are_not_skilled(self):
        baseline = {"trade_count": 100, "realized_trading_profit": 0, "history_exhausted": True}
        self.assertEqual(classify(baseline), "unskilled")
        baseline.update(realized_trading_profit=100, history_exhausted=False)
        self.assertEqual(classify(baseline), "unknown")

    def test_all_four_flow_directions_future_labels_and_wallet_cap(self):
        rows = [trade("a", "Yes", "BUY", 10000), trade("b", "No", "SELL"),
                trade("c", "Yes", "SELL"), trade("d", "No", "BUY"),
                trade("future", "Yes", "BUY"), trade("neutral", "Yes", "BUY"),
                trade("neutral", "Yes", "SELL"), trade("invalid", "Unknown", "BUY")]
        snapshots = [{"wallet": w, "as_of": 100, "trade_count": 100,
                      "realized_trading_profit": 1 if w in ("a", "c") else -1,
                      "history_exhausted": True} for w in ("a", "b", "c", "d")]
        snapshots.append({"wallet": "future", "as_of": 101, "trade_count": 100,
                          "realized_trading_profit": 100, "history_exhausted": True})
        result = cohorts({"start": 100, "end": 200, "condition_id": "condition",
                          "trades": rows, "pagination_exhausted": True}, snapshots, wallet_cap=20)
        for group in ("skilled_agree", "unskilled_agree", "skilled_disagree", "unskilled_disagree"):
            self.assertEqual(result["groups"][group]["wallets"], 1)
        self.assertEqual(result["groups"]["skilled_agree"]["capped_signed_flow_usdc"], 20)
        self.assertEqual(result["groups"]["unknown_agree"]["wallets"], 1)
        self.assertEqual(result["groups"]["unknown_neutral"]["wallets"], 1)
        self.assertEqual(result["future_snapshots_rejected"], 1)
        self.assertEqual(result["rows_skipped"], 1)

    def test_discovery_includes_closed_children_and_rejects_future_markets(self):
        events = [{"id": "1", "title": "Finance", "markets": [
            {"id": "1", "conditionId": "old", "slug": "old", "closed": True,
             "startDate": "2025-07-01", "endDate": "2025-12-31", "outcomes": '["Yes","No"]',
             "clobTokenIds": '["1","2"]'},
            {"id": "2", "conditionId": "future", "startDate": "2026-01-02"}]}]
        client = FakeClient([{"id": "120"}, events])
        result = discover(client, timestamp("2025-08-01"), timestamp("2026-01-01"), max_events=10)
        self.assertEqual([m["condition_id"] for m in result["markets"]], ["old"])
        self.assertTrue(result["discovery_exhausted"])
        self.assertNotIn("closed", client.calls[1][1])

    def test_prices_split_long_windows_and_keep_unavailable_distinct_from_zero(self):
        client = FakeClient([page([]), page([])])
        result = collect_prices(client, "token", 1, 16 * 86400 + 1)
        self.assertEqual(len(result["windows"]), 2)
        self.assertEqual(result["points"], [])
        self.assertEqual(client.calls[0][1]["end"], client.calls[1][1]["start"])


if __name__ == "__main__":
    unittest.main()
