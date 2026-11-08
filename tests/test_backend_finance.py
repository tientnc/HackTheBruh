import unittest
from unittest.mock import MagicMock, patch

from backend import main


class FinanceWalletEndpointTests(unittest.TestCase):
    def test_wallet_record_endpoints_query_tables_by_wallet_and_paginate(self):
        wallet = "wallet-a"
        trades = [{"wallet": wallet, "market_id": "f1", "source_row": 1}]
        returns = [{"wallet": wallet, "market_id": "f1", "usable": True}]

        trades_query = MagicMock()
        trades_query.execute.return_value.data = trades
        returns_query = MagicMock()
        returns_query.execute.return_value.data = returns
        for query in (trades_query, returns_query):
            query.select.return_value = query
            query.eq.return_value = query
            query.order.return_value = query
            query.range.return_value = query
        db = MagicMock()
        db.table.side_effect = [trades_query, returns_query]

        with patch.object(main, "_create_supabase_client", return_value=db):
            trade_result = main.get_wallet_research_trades(
                wallet, limit=25, offset=50
            )
            return_result = main.get_wallet_research_returns(
                wallet, limit=10, offset=20
            )

        self.assertEqual(trade_result["rows"], trades)
        self.assertEqual(trade_result["count"], 1)
        trades_query.eq.assert_called_once_with("wallet", wallet)
        trades_query.range.assert_called_once_with(50, 74)

        self.assertEqual(return_result["rows"], returns)
        self.assertEqual(return_result["count"], 1)
        returns_query.eq.assert_called_once_with("wallet", wallet)
        returns_query.range.assert_called_once_with(20, 29)


    def test_get_all_wallets_only_includes_finance_dataset_markets(self):
        markets = [
            {"dataset_key": "finance-2025-v1", "market_id": "f1"},
            {"dataset_key": "crypto-2025-v1", "market_id": "c1"},
        ]
        trades = [
            {"wallet": "wallet-a", "market_id": "f1"},
            {"wallet": "wallet-a", "market_id": "c1"},
            {"wallet": "wallet-b", "market_id": "f1"},
        ]
        with (
            patch.object(main, "get_markets", return_value=markets),
            patch.object(main, "_create_supabase_client", return_value=MagicMock()),
            patch.object(main, "_fetch_all", return_value=trades),
        ):
            result = main.get_all_wallets()

        self.assertEqual(result, [
            {
                "wallet_id": "wallet-a",
                "markets": [{"dataset_key": "finance-2025-v1", "market_id": "f1"}],
            },
            {
                "wallet_id": "wallet-b",
                "markets": [{"dataset_key": "finance-2025-v1", "market_id": "f1"}],
            },
        ])

    def test_get_all_wallets_respects_configured_wallet_limit(self):
        trades = [
            {"wallet": f"wallet-{wallet:03}", "market_id": "f1"}
            for wallet in range(75)
        ]
        with (
            patch.object(
                main,
                "get_markets",
                return_value=[{"dataset_key": "finance-2025-v1", "market_id": "f1"}],
            ),
            patch.object(main, "_create_supabase_client", return_value=MagicMock()),
            patch.object(main, "_fetch_all", return_value=trades),
        ):
            result = main.get_all_wallets()

        self.assertEqual(len(result), main.MAX_FINANCE_WALLETS)
        self.assertEqual(result[0]["wallet_id"], "wallet-000")
        self.assertEqual(
            result[-1]["wallet_id"],
            f"wallet-{main.MAX_FINANCE_WALLETS - 1:03}",
        )

    def test_trade_return_rows_calculate_cashflow_and_settlement_pnl(self):
        wallet_markets = [{
            "wallet_id": "wallet-a",
            "markets": [
                {"dataset_key": "finance-v1", "market_id": "m1"},
                {"dataset_key": "finance-v1", "market_id": "m2"},
                {"dataset_key": "finance-v1", "market_id": "m3"},
            ],
        }]
        markets = [{
            "dataset_key": "finance-v1",
            "market_id": "m1",
            "economic_cluster_id": "event-1",
            "category": "equities_and_corporate",
            "yes_outcome": 1,
            "label_available_at": 200,
        }, {
            "dataset_key": "finance-v1",
            "market_id": "m2",
            "economic_cluster_id": "event-2",
            "category": "commodities",
            "yes_outcome": 0,
            "label_available_at": 200,
        }, {
            "dataset_key": "finance-v1",
            "market_id": "m3",
            "economic_cluster_id": "event-3",
            "category": "rates_and_macro",
            "yes_outcome": 1,
            "label_available_at": 400,
        }]
        trades = [
            {
                "wallet": "wallet-a",
                "dataset_key": "finance-v1",
                "market_id": "m1",
                "side": "BUY",
                "outcome": "Yes",
                "size_shares": 10,
                "price": 0.4,
            },
            {
                "wallet": "wallet-a",
                "dataset_key": "finance-v1",
                "market_id": "m1",
                "side": "SELL",
                "outcome": "Yes",
                "size_shares": 2,
                "price": 0.7,
            },
            {
                "wallet": "wallet-a",
                "dataset_key": "finance-v1",
                "market_id": "m2",
                "side": "BUY",
                "outcome": "Yes",
                "size_shares": 2,
                "price": 0.5,
            },
            {
                "wallet": "wallet-a",
                "dataset_key": "finance-v1",
                "market_id": "m2",
                "side": "SELL",
                "outcome": "Yes",
                "size_shares": 3,
                "price": 0.6,
            },
            {
                "wallet": "wallet-a",
                "dataset_key": "finance-v1",
                "market_id": "m3",
                "side": "BUY",
                "outcome": "Yes",
                "size_shares": 10,
                "price": 0.5,
            },
        ]

        rows = main._trade_return_rows(wallet_markets, markets, trades, cutoff=300)

        self.assertEqual([row["market_id"] for row in rows["wallet-a"]], ["m1"])
        self.assertAlmostEqual(rows["wallet-a"][0]["reported_realized_pnl_usdc"], 5.4)
        self.assertAlmostEqual(rows["wallet-a"][0]["estimated_entry_basis_usdc"], 4.0)

    def test_batch_trade_edge_matches_buy_only_settlement_proxy(self):
        wallet_markets = [{
            "wallet_id": "wallet-a",
            "markets": [
                {"dataset_key": "finance-v1", "market_id": "m1"},
                {"dataset_key": "finance-v1", "market_id": "m2"},
            ],
        }]
        markets = [
            {"dataset_key": "finance-v1", "market_id": "m1",
             "yes_outcome": 1, "label_available_at": 100},
            {"dataset_key": "finance-v1", "market_id": "m2",
             "yes_outcome": 0, "label_available_at": 100},
        ]
        trades = [
            {"wallet": "wallet-a", "dataset_key": "finance-v1", "market_id": "m1",
             "side": "BUY", "outcome": "Yes", "size_shares": 10, "price": 0.4},
            {"wallet": "wallet-a", "dataset_key": "finance-v1", "market_id": "m2",
             "side": "BUY", "outcome": "No", "size_shares": 10, "price": 0.3},
        ]

        result = main._trade_edge_by_wallet(wallet_markets, markets, trades, cutoff=200)

        self.assertAlmostEqual(result["wallet-a"][0], 0.65)
        self.assertEqual(result["wallet-a"][1], 2)

    def test_median_exclusion_handles_peer_benchmarks_without_resorting(self):
        self.assertEqual(main._median_excluding([1.0, 3.0, 8.0, 10.0], None), 5.5)
        self.assertEqual(main._median_excluding([1.0, 3.0, 8.0, 10.0], 0), 8.0)
        self.assertEqual(main._median_excluding([1.0, 3.0, 8.0, 10.0], 2), 3.0)
        self.assertIsNone(main._median_excluding([1.0], 0))

    def test_finance_results_use_trade_derived_rows_for_peer_benchmarks(self):
        wallets = [
            {
                "wallet_id": "wallet-skilled",
                "markets": [{"dataset_key": "finance-2025-v1", "market_id": "f1"}],
            },
            {
                "wallet_id": "wallet-unskilled",
                "markets": [{"dataset_key": "finance-2025-v1", "market_id": "f1"}],
            },
        ]
        market_rows = [{
            "dataset_key": "finance-2025-v1",
            "market_id": "f1",
            "yes_outcome": 1,
            "label_available_at": 100,
        }]
        trade_rows = [
            {"wallet": "wallet-skilled", "dataset_key": "finance-2025-v1",
             "market_id": "f1", "side": "BUY", "outcome": "Yes",
             "size_shares": 10, "price": 0.4},
            {"wallet": "wallet-unskilled", "dataset_key": "finance-2025-v1",
             "market_id": "f1", "side": "BUY", "outcome": "Yes",
             "size_shares": 10, "price": 0.8},
        ]

        def summarize(_db, wallet, _rows, _cutoff, **_kwargs):
            is_skilled = wallet == "wallet-skilled"
            return {
                "wallet": wallet,
                "realized_pnl_usdc": 20 if is_skilled else 10,
                "estimated_roi": 0.4 if is_skilled else 0.2,
                "profitable_market_rate": 0.8 if is_skilled else 0.6,
                "market_relative_edge_proxy": 0.3 if is_skilled else 0.1,
                "independent_resolved_markets": 6,
                "confidence_weight": 0.7 if is_skilled else 0.5,
            }

        with (
            patch.object(main, "get_all_wallets", return_value=wallets),
            patch.object(main, "_create_supabase_client", return_value=MagicMock()),
            patch.object(
                main,
                "_load_finance_trade_evidence",
                return_value=(market_rows, trade_rows),
            ),
            patch.object(main, "_summarize_wallet", side_effect=summarize) as summarize_wallet,
            patch.object(main, "_edge_proxy", side_effect=AssertionError("edge should use batch rows")),
            patch.object(main, "_get_returns", side_effect=AssertionError("research_returns must not be queried")),
        ):
            result = main.get_wallets_result()

        self.assertEqual(
            summarize_wallet.call_args_list[0].args[2][0]["market_id"],
            "f1",
        )
        self.assertEqual(result, {
            "wallet-skilled": "skilled",
            "wallet-unskilled": "unskilled",
        })

    def test_finance_check_reports_trade_derived_metrics(self):
        wallet = "wallet-a"
        wallet_entry = {
            "wallet_id": wallet,
            "markets": [{"dataset_key": "finance-2025-v1", "market_id": "f1"}],
        }
        market_rows = [{
            "dataset_key": "finance-2025-v1",
            "market_id": "f1",
            "economic_cluster_id": "event-1",
            "category": "etfs_and_digital_finance",
            "yes_outcome": 1,
            "label_available_at": 50,
        }]
        trade_rows = [{
            "wallet": wallet,
            "dataset_key": "finance-2025-v1",
            "market_id": "f1",
            "side": "BUY",
            "outcome": "Yes",
            "size_shares": 10,
            "price": 0.5,
        }]
        metrics = {
            "wallet": wallet,
            "realized_pnl_usdc": 5.0,
            "estimated_roi": 1.0,
            "profitable_market_rate": 1.0,
            "completed_markets": 1,
            "independent_resolved_markets": 1,
            "confidence_weight": 1 / 21,
            "market_relative_edge_proxy": 0.5,
            "edge_eligible_markets": 1,
        }
        with (
            patch.object(main, "_create_supabase_client", return_value=MagicMock()),
            patch.object(main, "get_all_wallets", return_value=[wallet_entry]),
            patch.object(
                main,
                "_load_finance_trade_evidence",
                return_value=(market_rows, trade_rows),
            ),
            patch.object(main, "_summarize_wallet", return_value=metrics),
        ):
            result = main.check_finance_wallet(wallet, cutoff=100)

        self.assertTrue(result["included_in_current_finance_wallet_batch"])
        self.assertEqual(result["finance_trade_market_count"], 1)
        self.assertEqual(result["resolved_trade_market_count"], 1)
        self.assertFalse(result["would_stats_be_none"])
        self.assertEqual(result["reason"], "trade_derived_stats_available")
        self.assertEqual(result["trade_derived_returns"][0]["market_id"], "f1")


if __name__ == "__main__":
    unittest.main()
