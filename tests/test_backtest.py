import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from polyresearch.artifacts import manifest, verify
from polyresearch.backtest import build, fit, flow_features, predict, price_at, score
from polyresearch.dataset import dump, table


class BacktestTests(unittest.TestCase):
    def test_quotes_must_be_available_recent_and_not_settlement(self):
        def quote(at, resolution=60, token="yes"):
            return {"token_id": token, "resolution_seconds": resolution,
                    "available_at": at, "timestamp": at-resolution, "price": .5}
        rows = [quote(90), quote(101), quote(99, 0), quote(95, token="no")]
        self.assertEqual(price_at(rows, "yes", 100, 20)["available_at"], 90)
        self.assertIsNone(price_at(rows, "yes", 100, 5))

    def test_flows_use_past_trades_direction_and_fixed_cohort_denominator(self):
        cohorts = {"members": {"top_decile": ["a", "inactive"], "bottom_decile": ["b"]}}
        def trade(wallet, side, outcome, size, at=99):
            return dict(wallet=wallet, side=side, outcome=outcome, size_shares=size, timestamp=at)
        rows = [trade("a", "BUY", "No", 500), trade("b", "SELL", "No", 2000),
                trade("a", "BUY", "Yes", 10000, 100), trade("a", "BUY", "Yes", 10000, 0)]
        result = flow_features(rows, 100, cohorts, window_seconds=20)
        self.assertEqual(result["top_decile_flow"], -.25)
        self.assertEqual(result["bottom_decile_flow"], 1)
        self.assertEqual(result["top_decile_active_wallets"], 1)
        self.assertEqual(result["all_wallet_flow"], .25)

    def test_no_signal_is_exactly_market_and_brier_uses_same_samples(self):
        self.assertEqual(predict(.12345, [0, 0], [10, -10]), .12345)
        self.assertEqual(fit([{"market_probability": .2, "yes_outcome": 1, "x": 0}], ["x"]), [0])
        rows = [{"market_probability": .5, "yes_outcome": 1, "model": .8},
                {"market_probability": .5, "yes_outcome": 0, "model": .2}]
        self.assertAlmostEqual(score(rows, "model")["brier_skill_vs_market"], .84)

    def test_model_fit_cannot_see_future_labels(self):
        # Changing held-out labels cannot change the fitted model.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, wallets = root / "dataset", root / "wallets"
            dump(dataset / "manifest.json", {})
            dump(wallets / "manifest.json", {})
            dump(wallets / "cohorts.json", {"as_of": 100, "decile_size": 1,
                 "members": {"top_decile": ["a"], "bottom_decile": ["b"]}})
            markets = []
            from polyresearch.research import iso
            for name, cutoff, label_at in [("train", 200, 300), ("immature", 250, 500),
                                           ("test", 500, 700), ("too_early", 90, 200)]:
                markets.append({"market_id": name, "folder": name, "economic_cluster_id": name,
                                "label_available_at": label_at, "scheduled_end_date": iso(cutoff+3600),
                                "trading_start": iso(1), "yes_outcome": 1})
                folder = dataset / name
                table(folder / "outcomes.csv", [{"outcome": "Yes", "token_id": "yes"}], ["outcome", "token_id"])
                quote = dict(token_id="yes", resolution_seconds=10, timestamp=cutoff-20,
                             available_at=cutoff-10, price=.5)
                table(folder / "prices.csv.gz", [quote], list(quote))
                trade = dict(wallet="a", timestamp=cutoff-1, side="BUY", outcome="Yes", size_shares=500)
                table(folder / "trades.csv.gz", [trade], list(trade))
            table(dataset / "markets.csv", markets, list(markets[0]))
            with contextlib.redirect_stdout(io.StringIO()):
                summary = build(dataset, wallets, root / "out1", test_start=400, lead_hours=1)
                markets[2]["yes_outcome"] = 0
                table(dataset / "markets.csv", markets, list(markets[0]))
                build(dataset, wallets, root / "out2", test_start=400, lead_hours=1)
            self.assertEqual(summary["calibration_markets"], 1)
            self.assertEqual(summary["test_markets"], 1)
            self.assertEqual(summary["excluded_markets"], 2)
            self.assertEqual(json.loads((root / "out1/model.json").read_text()),
                             json.loads((root / "out2/model.json").read_text()))

    def test_manifest_detects_changed_artifacts_and_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            dump(source, {"input": 1})
            out = root / "out"
            dump(out / "result.json", {"result": 2})
            manifest(out, [source])
            self.assertEqual(verify(out), 1)
            dump(source, {"input": 3})
            with self.assertRaises(ValueError):
                verify(out)


if __name__ == "__main__":
    unittest.main()
