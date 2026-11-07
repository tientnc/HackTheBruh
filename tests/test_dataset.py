import csv
import tempfile
import unittest
from pathlib import Path

from polyresearch.dataset import END, START, catalog_rows, read_table, select, subfield, table


class DatasetTests(unittest.TestCase):
    def test_catalog_uses_child_dates_and_labels_current_prices(self):
        raw = {"collected_at": "2026-11-07T00:00:00Z", "events": [{
            "id": "10", "title": "Gold", "tags": [{"slug": "finance"}], "markets": [
                {"id": "1", "conditionId": "old", "question": "Gold above $3000?",
                 "startDate": "2025-01-01", "endDate": "2025-12-31", "closed": True,
                 "outcomes": '["Yes","No"]', "clobTokenIds": '["a","b"]',
                 "outcomePrices": '["1","0"]'},
                {"id": "2", "conditionId": "new", "startDate": "2026-01-01"},
                {"id": "3", "conditionId": "expired", "endDate": "2025-07-01"}]}]}
        markets, outcomes = catalog_rows(raw)
        self.assertEqual([m["condition_id"] for m in markets], ["old"])
        self.assertEqual(markets[0]["subfield"], "commodities")
        self.assertEqual(outcomes[0]["price_now"], "1")
        self.assertNotIn("price", outcomes[0])

    def test_selection_spreads_events_and_ignores_prices(self):
        markets, outcomes = [], []
        for i in range(1, 7):
            markets.append({"condition_id": str(i), "market_id": str(i),
                            "event_id": "a" if i <= 4 else "b", "subfield": "commodities",
                            "start_date": "2025-01-01", "end_date": "2026-01-01"})
            outcomes.extend({"condition_id": str(i), "outcome": label, "token_id": f"{i}-{label}",
                             "price_now": "1"} for label in ("Yes", "No"))
        chosen = select(markets, outcomes, 4)
        self.assertEqual([m["market_id"] for m in chosen], ["1", "2", "5", "6"])
        for outcome in outcomes:
            outcome["price_now"] = "0"
        self.assertEqual(select(markets, outcomes, 4), chosen)

    def test_selection_prefers_scheduled_full_window(self):
        base = {"start_date": "2025-01-01", "subfield": "rates_and_macro"}
        markets = [{**base, "condition_id": "a", "event_id": "a", "market_id": "1",
                    "end_date": "2025-08-15"},
                   {**base, "condition_id": "b", "event_id": "b", "market_id": "2",
                    "end_date": "2025-12-31"}]
        outcomes = [{"condition_id": m["condition_id"], "outcome": label, "token_id": label}
                    for m in markets for label in ("Yes", "No")]
        self.assertEqual(select(markets, outcomes, 1)[0]["market_id"], "2")

    def test_gzip_table_round_trip_keeps_large_ids_as_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rows.csv.gz"
            token = "1234567890123456789012345678901234567890"
            table(path, [{"token_id": token, "price": .123}], ["token_id", "price"])
            rows = read_table(path)
            self.assertEqual(rows, [{"token_id": token, "price": "0.123"}])


if __name__ == "__main__":
    unittest.main()
