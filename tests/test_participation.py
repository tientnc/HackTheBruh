import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyresearch.dataset import dump, table
from polyresearch.participation import (FEATURES, actions, build, fit_rate_model, groups_at,
                                        predict_count, window_rows)
from polyresearch.position_evidence import normalize


class ParticipationTests(unittest.TestCase):
    def test_position_sides_aggregate_and_latest_economics_controls_availability(self):
        market = dict(condition_id="c", market_id="m", economic_cluster_id="e", subfield="finance", label_available_at=100)
        def position(token, pnl, at):
            return dict(proxy_wallet="A", token_id=token, condition_id="c", realized_pnl=pnl,
                        total_size=10, avg_price=.5, last_event_at=at, first_entry_at=20)
        one, two = position("yes", 4, 90), position("no", -2, 110)
        row = normalize(market, [one, two, one])[0]
        self.assertEqual(row["position_tokens"], 2)
        self.assertEqual(row["available_at"], 110)
        self.assertEqual(row["reported_realized_pnl_usdc"], 2)
        self.assertAlmostEqual(row["reported_return_proxy"], .2)
        self.assertFalse(normalize(market, [{**one, "avg_price": 0}])[0]["usable_return_proxy"])
        with self.assertRaises(ValueError):
            normalize(market, [one, {**one, "realized_pnl": 100}])

    def test_group_rule_uses_winner_mean_repeated_history_and_past_clocks(self):
        returns = []
        for event, at in [("e1", 10), ("e2", 20), ("future", 100)]:
            for wallet, value in [("a", .02), ("b", .04), ("c", .06), ("d", .88)]:
                returns.append(dict(wallet=wallet, economic_cluster_id=event, usable_return_proxy=True,
                                    available_at=at, reported_return_proxy=value, reported_realized_pnl_usdc=value*100))
        result = groups_at(returns, 100, min_markets=2)
        self.assertEqual(result["d"]["group"], "skilled_proxy")
        self.assertEqual(result["a"]["group"], "unskilled_proxy")
        self.assertEqual(result["d"]["earlier_comparable_markets"], 2)
        self.assertEqual(groups_at(returns, 20, 2)["d"]["group"], "unknown")
        self.assertEqual(groups_at([{**r, "reported_realized_pnl_usdc": 0} for r in returns], 100), {})

    def test_unique_wallet_counts_preserve_both_sides_tokens_and_window_end(self):
        trades = [(99,"a","BUY","yes"), (100,"a","BUY","yes"), (101,"a","BUY","no"),
                  (102,"a","SELL","no"), (103,"outside","BUY","yes"), (107,"b","BUY","yes")]
        times = [r[0] for r in trades]
        sides,tokens = actions(trades,times,100,107)
        self.assertEqual(sides["BUY"], {"a","outside"})
        self.assertEqual(tokens[("BUY","no")], {"a"})
        market=dict(market_id="m",economic_cluster_id="e",trading_start="1970-01-01",scheduled_end_date="1970-01-02",subfield="finance")
        candidates=[dict(wallet="a",first_trade_at=1),dict(wallet="b",first_trade_at=107)]
        groups={"a":{"group":"skilled_proxy"},"b":{"group":"unskilled_proxy"}}
        rows,_,cov=window_rows(market,100,7,candidates,groups,trades,times,closed_at=200)
        self.assertEqual([r["actual_wallets"] for r in rows if r["group"]=="skilled_proxy"],[1,1])
        self.assertEqual(cov["actual_candidate_participants"],1)
        self.assertEqual(cov["actual_outside_candidate_participants"],1)
        self.assertEqual(cov["eligible_candidate_wallets"],1)

    def test_count_model_stays_within_candidate_group_size(self):
        rows=[{**{f:0 for f in FEATURES}, "group_size":10,"actual_wallets":2} for _ in range(3)]
        model=fit_rate_model(rows)
        prediction=predict_count(model,rows[0])
        self.assertTrue(0 <= prediction <= 10)
        self.assertAlmostEqual(prediction,2,places=3)
        self.assertEqual(predict_count(None,{"group_size":0}),0)

    def test_changing_later_labels_cannot_change_fitted_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            earlier,later,returns=root/"earlier",root/"later",root/"returns"
            for folder,event in [(earlier,"early"),(later,"late")]:
                dump(folder/"validation.json",{"passed":True})
                dump(folder/"manifest.json",{})
                table(folder/"markets.csv",[{"economic_cluster_id":event}],["economic_cluster_id"])
            dump(returns/"summary.json",{"errors":0})
            dump(returns/"manifest.json",{})
            table(returns/"wallet_market_returns.csv.gz",[],["wallet"])
            candidate=dict(wallet="a",first_trade_at=1)
            row={**{f:0 for f in FEATURES},"group_size":1,"actual_wallets":1,
                 "market_id":"early","group":"unknown","side":"BUY","recent_wallets":0}
            train=[row]
            def run(out,actual):
                test=[{**row,"market_id":"late","actual_wallets":actual}]
                with patch("polyresearch.participation.rank_wallets",return_value=([candidate],1)), \
                     patch("polyresearch.participation.examples",side_effect=[(train,[],[],[]),(test,[],[],[])]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    build(earlier,later,returns,out,fit_at=100)
            run(root/"out1",0)
            run(root/"out2",1)
            self.assertEqual(json.loads((root/"out1/model.json").read_text()),
                             json.loads((root/"out2/model.json").read_text()))


if __name__ == "__main__":
    unittest.main()
