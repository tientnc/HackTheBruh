import tempfile
import unittest
from pathlib import Path

from polyresearch.dataset import table
from polyresearch.research import timestamp
from polyresearch.wallet_metrics import (adjusted_qvalues, brier_skill, closed_position_metrics,
                                        event_evidence, forecast_is_available, historical_pnl, sign_randomization)


class WalletMetricsTests(unittest.TestCase):
    def test_brier_skill_compares_probabilities_on_same_samples(self):
        result = brier_skill([.8, .2], [.5, .5], [1, 0])
        self.assertAlmostEqual(result["brier_skill_score"], .84)
        self.assertEqual(brier_skill([.5], [.5], [1])["brier_skill_score"], 0)
        self.assertIsNone(brier_skill([1], [1], [1])["brier_skill_score"])
        with self.assertRaises(ValueError):
            brier_skill([1.1], [.5], [1])

    def test_reconciled_profit_roi_and_profitable_position_win_rate(self):
        base = {"closed_at": 50, "available_at": 60, "reconciled": True,
                "cost_basis_usdc": 100, "fees_usdc": 2, "other_costs_usdc": 1,
                "capital_deployed_usdc": 100}
        rows = [{**base, "proceeds_usdc": 120}, {**base, "proceeds_usdc": 90},
                {**base, "proceeds_usdc": 1000, "available_at": 100}]
        result = closed_position_metrics(rows, 100)
        self.assertEqual(result["net_realized_pnl_usdc"], 4)
        self.assertEqual(result["roi_on_supplied_deployed_capital"], .02)
        self.assertEqual(result["profitable_closed_position_win_rate"], .5)
        bad = {**base, "proceeds_usdc": 120}
        del bad["fees_usdc"]
        with self.assertRaises(KeyError):
            closed_position_metrics([bad], 100)

    def test_five_perfect_events_do_not_prove_two_sided_sign_skill(self):
        self.assertEqual(sign_randomization([1] * 5), .0625)
        self.assertEqual(sign_randomization([1, -1]), 1)
        self.assertIsNone(sign_randomization([]))

    def test_fdr_is_joint_and_by_is_more_conservative(self):
        p = {"a": .001, "b": .02, "c": .5}
        bh, by = adjusted_qvalues(p, "BH"), adjusted_qvalues(p, "BY")
        self.assertAlmostEqual(bh["a"], .003)
        self.assertTrue(all(by[k] >= bh[k] for k in p))
        self.assertEqual(adjusted_qvalues({}), {})

    def test_pnl_only_uses_observations_strictly_before_cutoff(self):
        response = {"data": {"points": [
            {"timestamp": 99, "realized_market_pnl": 10, "realized_combo_pnl": 2},
            {"timestamp": 100, "realized_market_pnl": 10000, "realized_combo_pnl": 0}]}}
        result = historical_pnl(response, 100)
        self.assertEqual(result["reported_lifetime_realized_pnl_usdc"], 12)
        self.assertEqual(result["pnl_observed_at"], 99)
        self.assertEqual(result["pnl_age_seconds"], 1)
        self.assertIsNone(historical_pnl({"data": None}, 100)["reported_lifetime_realized_pnl_usdc"])

    def test_forecast_cannot_use_quote_that_became_available_later(self):
        row = dict(issued_at=50, market_quote_at=40, market_quote_available_at=45, outcome_available_at=60)
        self.assertTrue(forecast_is_available(row, 100))
        self.assertFalse(forecast_is_available({**row, "market_quote_available_at": 51}, 100))
        self.assertFalse(forecast_is_available(row, 60))

    def test_evidence_adjusts_sell_direction_and_rejects_future_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markets = [{"market_id": "1", "economic_cluster_id": "e1", "subfield": "finance",
                        "label_available_at": 100, "yes_outcome": 0, "folder": "one"},
                       {"market_id": "2", "economic_cluster_id": "e2", "subfield": "finance",
                        "label_available_at": 200, "yes_outcome": 1, "folder": "future"}]
            table(root / "markets.csv", markets, list(markets[0]))
            table(root / "one/wallets.csv", [{"wallet": "a"}], ["wallet"])
            # Sell YES at .7, later YES loses: +.7 edge/share and correct NO direction.
            trade = {"wallet": "a", "timestamp": 90, "size_shares": 10,
                     "price": .7, "outcome": "Yes", "side": "SELL"}
            table(root / "one/trades.csv.gz", [trade], list(trade))
            observations, population, count = event_evidence(root, 150)
            self.assertEqual(count, 1)
            self.assertEqual(population, {"a"})
            self.assertAlmostEqual(observations[0]["event_market_relative_edge"], .7)
            self.assertEqual(observations[0]["dominant_direction_correct"], 1)
            self.assertAlmostEqual(observations[0]["implied_directional_success_proxy"], .3)
            self.assertEqual(event_evidence(root, 150, min_lead_hours=1)[0], [])


if __name__ == "__main__":
    unittest.main()
