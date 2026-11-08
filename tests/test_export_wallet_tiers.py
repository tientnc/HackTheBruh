import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

EXPORT_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "wallet-tiers"
    / "v1"
    / "export_tiers.py"
)
SPEC = importlib.util.spec_from_file_location("export_tiers", EXPORT_SCRIPT)
export_tiers = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(export_tiers)


class WalletTierExportTests(unittest.TestCase):
    def test_fetches_both_routes_and_writes_requested_csv_columns(self):
        responses = [
            [{"wallet_id": "wallet-a", "markets": []}, {"wallet_id": "wallet-b", "markets": []}],
            {"wallet-a": "skilled", "wallet-b": "unskilled"},
        ]
        requested_urls = []

        class FakeResponse:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(self.value).encode()

        def fake_urlopen(url, timeout):
            requested_urls.append((url, timeout))
            return FakeResponse(responses.pop(0))

        with tempfile.TemporaryDirectory() as folder:
            output_file = Path(folder) / "tiers.csv"
            with patch.object(export_tiers, "urlopen", side_effect=fake_urlopen):
                count = export_tiers.export_tiers("http://localhost:8000/", output_file)

            with output_file.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(count, 2)
        self.assertEqual(rows, [
            ["wallet", "tier"],
            ["wallet-a", "skilled"],
            ["wallet-b", "unskilled"],
        ])
        self.assertEqual(requested_urls, [
            ("http://localhost:8000/wallets/finance", 600),
            ("http://localhost:8000/wallets/finance/results", 600),
        ])

    def test_missing_classification_fails_instead_of_writing_partial_csv(self):
        responses = [[{"wallet_id": "wallet-a", "markets": []}], {}]

        class FakeResponse:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(self.value).encode()

        with tempfile.TemporaryDirectory() as folder:
            output_file = Path(folder) / "tiers.csv"
            with patch.object(
                export_tiers, "urlopen",
                side_effect=lambda *_args, **_kwargs: FakeResponse(responses.pop(0)),
            ):
                with self.assertRaisesRegex(ValueError, "No classification"):
                    export_tiers.export_tiers("http://localhost:8000", output_file)
            self.assertFalse(output_file.exists())


if __name__ == "__main__":
    unittest.main()
