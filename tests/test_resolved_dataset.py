import unittest

from polyresearch.resolved_dataset import candidates, economic_cluster, parse_time, verified_resolution
from polyresearch.research import timestamp


class ResolvedDatasetTests(unittest.TestCase):
    def market(self):
        return {"id": "1", "conditionId": "condition", "question": "IPO in 2025?",
                "startDate": "2025-07-01", "closedTime": "2025-09-01T00:00:00Z",
                "closed": True, "umaResolutionStatus": "resolved",
                "outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]',
                "clobTokenIds": '["yes","no"]'}

    def test_candidates_require_actual_close_window_and_sufficient_lifetime(self):
        market = self.market()
        raw = {"events": [{"id": "event", "markets": [market]}]}
        self.assertEqual(len(candidates(raw)), 1)
        market["closedTime"] = "2025-07-31"
        self.assertEqual(candidates(raw), [])
        market["closedTime"] = "2025-09-01"
        market["startDate"] = "2025-08-31"
        self.assertEqual(candidates(raw), [])

    def test_resolution_uses_binary_oracle_price_and_conservative_time(self):
        market = self.market()
        resolution = {"condition_id": "condition", "status": "resolved",
                      "price": "1000000000000000000", "last_update_timestamp": str(timestamp("2025-09-02"))}
        result = verified_resolution(market, resolution)
        self.assertEqual(result["yes_outcome"], 1)
        self.assertEqual(result["label_available_at"], timestamp("2025-09-02"))
        resolution["price"] = "500000000000000000"
        self.assertIsNone(verified_resolution(market, resolution))

    def test_conflicting_or_nonfinal_outcomes_are_rejected(self):
        market = self.market()
        resolution = {"condition_id": "condition", "status": "resolved", "payouts": [0, 1000000],
                      "resolved_at": "2025-09-01T00:00:00Z"}
        self.assertIsNone(verified_resolution(market, resolution))
        resolution.update(payouts=[1000000, 0], status="proposed")
        self.assertIsNone(verified_resolution(market, resolution))

    def test_numeric_and_iso_lifecycle_timestamps(self):
        self.assertEqual(parse_time("1756684800"), parse_time("2025-09-01T00:00:00Z"))

    def test_explicit_later_window_is_used_by_selection_and_resolution(self):
        market={**self.market(),"startDate":"2025-12-01","closedTime":"2026-01-15"}
        start,end=timestamp("2026-01-01"),timestamp("2026-02-01")
        self.assertEqual(candidates({"events":[{"id":"e","markets":[market]}]}),[])
        self.assertEqual(len(candidates({"events":[{"id":"e","markets":[market]}]},start=start,end=end)),1)
        resolution={"condition_id":"condition","status":"resolved","payouts":[1000000,0],"resolved_at":"2026-01-15"}
        self.assertIsNotNone(verified_resolution(market,resolution,start,end))

    def test_same_asset_week_ladders_are_one_family_across_parent_ids(self):
        market = self.market()
        a = economic_cluster(market, {"id": "a", "title": "Will Apple (AAPL) finish week above $200?"})
        b = economic_cluster(market, {"id": "b", "title": "Apple (AAPL) closes week at ___?"})
        self.assertEqual(a, b)

    def test_ipo_families_group_generic_and_named_events(self):
        a = {**self.market(), "question": "Will Medline IPO in 2025?"}
        b = {**self.market(), "question": "Will Medline Industries IPO before 2027?"}
        self.assertEqual(economic_cluster(a, {"id": "a", "title": "IPOs in 2025?"}),
                         economic_cluster(b, {"id": "b", "title": "IPOs before 2027?"}))


if __name__ == "__main__":
    unittest.main()
