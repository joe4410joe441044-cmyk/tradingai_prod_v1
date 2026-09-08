from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from backend.bot_manager.bot_manager import BotManager
from backend.execution.kucoin_trade import (
    KucoinTradeClient,
    account_status_total_pnl_today,
    normalize_kucoin_realized_pnl_today,
    normalize_kucoin_risk_ratio,
    utc_day_window,
)


DAY_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
NOON = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
DAY_START_MS = int(DAY_START.timestamp() * 1000)
NOON_MS = int(NOON.timestamp() * 1000)


def pnl_row(offset, amount, *, status="Completed", when=NOON_MS, **extra):
    return {
        "offset": offset,
        "currency": "USDT",
        "amount": str(amount),
        "fee": "999",  # metadata: RealisedPNL.amount is already net
        "type": "RealisedPNL",
        "remark": f"row-{offset}",
        "status": status,
        "time": when,
        **extra,
    }


class AccountStatusFinancialContractTest(unittest.TestCase):
    def test_risk_ratio_is_normalized_from_ratio_to_display_percent(self):
        self.assertEqual(normalize_kucoin_risk_ratio("0"), 0.0)
        self.assertEqual(normalize_kucoin_risk_ratio("0.25"), 25.0)
        self.assertEqual(normalize_kucoin_risk_ratio("1"), 100.0)
        for value in (None, "", True, "bad", -0.1, float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(normalize_kucoin_risk_ratio(value))

    def test_utc_day_boundary_is_explicit_and_timezone_aware(self):
        start, observed, start_ms, end_ms = utc_day_window(NOON)
        self.assertEqual(start, DAY_START)
        self.assertEqual(observed, NOON)
        self.assertEqual(start_ms, DAY_START_MS)
        self.assertEqual(end_ms, NOON_MS)
        with self.assertRaises(TypeError):
            utc_day_window(datetime(2026, 9, 8, 12))

    def test_wallet_balance_matrix_never_aliases_equity(self):
        scenarios = [
            ("positive-unrealized", "101.5", "100", "1.5", 100.0),
            ("negative-unrealized", "98.5", "100", "-1.5", 100.0),
            ("flat", "100", "100", "0", 100.0),
            ("authoritative-zero", "1.5", "0", "1.5", 0.0),
            ("missing-wallet", "101.5", None, "1.5", None),
        ]
        for name, equity, margin_balance, unrealized, expected in scenarios:
            with self.subTest(name=name):
                data = {
                    "currency": "USDT",
                    "accountEquity": equity,
                    "unrealisedPNL": unrealized,
                }
                if margin_balance is not None:
                    data["marginBalance"] = margin_balance
                response = Mock()
                response.json.return_value = {"code": "200000", "data": data}
                client = KucoinTradeClient(api_key="k", api_secret="s", passphrase="p")
                client.session.get = Mock(return_value=response)
                overview = client.get_account_overview()
                self.assertEqual(overview["walletBalance"], expected)
                self.assertEqual(overview["equity"], float(equity))

    def test_realized_pnl_includes_completed_and_pending_net_amounts(self):
        rows = [
            pnl_row(20, "3.50"),
            pnl_row(-1, "-1.25", status="Pending"),
        ]
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                rows, start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            2.25,
        )

    def test_realized_pnl_excludes_cash_movements_and_out_of_window_rows(self):
        rows = [
            pnl_row(20, "4"),
            pnl_row(19, "100", type="Deposit"),
            pnl_row(18, "100", type="Withdrawal"),
            pnl_row(17, "100", type="Transfer"),
            pnl_row(16, "100", when=DAY_START_MS - 1),
            pnl_row(15, "100", when=NOON_MS + 1),
        ]
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                rows, start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            4.0,
        )

    def test_utc_boundary_includes_midnight_and_excludes_prior_millisecond(self):
        rows = [
            pnl_row(3, "100", when=DAY_START_MS - 1),
            pnl_row(2, "2", when=DAY_START_MS),
            pnl_row(1, "3", when=DAY_START_MS + 1),
        ]
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                rows, start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            5.0,
        )

    def test_realised_pnl_amount_is_already_net_of_fee_and_funding(self):
        row = pnl_row(1, "-2.5", fee="1000", remark="funding-and-fees-net")
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                [row], start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            -2.5,
        )

    def test_empty_and_zero_ledgers_are_authoritative_zero(self):
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                [], start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            0.0,
        )
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                [pnl_row(1, "0")], start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            0.0,
        )

    def test_page_overlap_is_deduplicated_and_conflicts_fail_closed(self):
        row = pnl_row(20, "3")
        self.assertEqual(
            normalize_kucoin_realized_pnl_today(
                [row, dict(row)], start_ms=DAY_START_MS, end_ms=NOON_MS
            ),
            3.0,
        )
        conflict = dict(row, amount="4")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            normalize_kucoin_realized_pnl_today(
                [row, conflict], start_ms=DAY_START_MS, end_ms=NOON_MS
            )

    def test_daily_reader_completes_pagination_and_reuses_success_cache(self):
        client = KucoinTradeClient(api_key="k", api_secret="s", passphrase="p")
        page_one = {
            "dataList": [
                pnl_row(-1, "0.5", status="Pending"),
                pnl_row(20, "3"),
                pnl_row(10, "2"),
            ],
            "hasMore": True,
        }
        page_two = {
            "dataList": [pnl_row(10, "2"), pnl_row(5, "-1")],
            "hasMore": False,
        }
        client.get_futures_transaction_history = Mock(
            side_effect=[page_one, page_two]
        )

        first = client.get_realized_pnl_today(now=NOON)
        second = client.get_realized_pnl_today(now=NOON)

        self.assertEqual(first["value"], 4.5)
        self.assertTrue(first["complete"])
        self.assertEqual(first["timezone"], "UTC")
        self.assertEqual(second, first)
        self.assertEqual(client.get_futures_transaction_history.call_count, 2)
        second_call = client.get_futures_transaction_history.call_args_list[1]
        self.assertEqual(second_call.kwargs["offset"], 10)

    def test_daily_reader_does_not_cache_an_api_failure(self):
        client = KucoinTradeClient(api_key="k", api_secret="s", passphrase="p")
        client.get_futures_transaction_history = Mock(
            side_effect=[RuntimeError("api down"), {"dataList": [], "hasMore": False}]
        )
        with self.assertRaisesRegex(RuntimeError, "api down"):
            client.get_realized_pnl_today(now=NOON)
        result = client.get_realized_pnl_today(now=NOON)
        self.assertEqual(result["value"], 0.0)
        self.assertEqual(client.get_futures_transaction_history.call_count, 2)

    @patch("backend.execution.kucoin_trade.requests.Session.get")
    def test_overview_uses_direct_wallet_balance_and_normalized_margin_ratio(self, request_get):
        request_get.return_value.json.return_value = {
            "code": "200000",
            "data": {
                "currency": "USDT",
                "accountEquity": "101.5",
                "marginBalance": "100",
                "unrealisedPNL": "1.5",
                "riskRatio": "0.0588",
            },
        }
        client = KucoinTradeClient(api_key="k", api_secret="s", passphrase="p")
        overview = client.get_account_overview()
        self.assertEqual(overview["walletBalance"], 100.0)
        self.assertEqual(overview["riskRatio"], "0.0588")
        self.assertEqual(overview["marginRatio"], 5.88)

        request_get.return_value.json.return_value["data"].pop("marginBalance")
        overview = client.get_account_overview()
        self.assertIsNone(overview["walletBalance"])
        self.assertEqual(overview["equity"], 101.5)

    @patch.object(KucoinTradeClient, "credentials_present", return_value=True)
    def test_bot_manager_propagates_financial_contract(self, _credentials):
        client = Mock()
        client.get_account_overview.return_value = {
            "accountType": "KUCOIN_FUTURES",
            "permission": "READ_ONLY",
            "balance": 101.5,
            "equity": 101.5,
            "availableBalance": 90,
            "walletBalance": 100,
            "unrealizedPnl": 1.5,
            "marginUsed": 10,
            "availableMargin": 90,
            "marginRatio": 5.88,
        }
        client.get_realized_pnl_today.return_value = {
            "value": 3.0,
            "source": "KUCOIN_FUTURES_REALISED_PNL_LEDGER",
            "observedAt": "2026-09-08T12:00:00Z",
            "dayStart": "2026-09-08T00:00:00Z",
            "complete": True,
        }
        client.get_positions.return_value = []
        bot = BotManager()
        bot.account_read_client = client
        bot.account_read_client_exchange = "kucoin"

        snapshot = bot._refresh_real_account_snapshot("kucoin")
        self.assertEqual(snapshot["walletBalance"], 100)
        self.assertEqual(snapshot["realizedPnlToday"], 3.0)
        self.assertEqual(snapshot["totalPnlToday"], 4.5)
        self.assertEqual(snapshot["marginRatio"], 5.88)
        self.assertEqual(snapshot["dailyPnlDayStart"], "2026-09-08T00:00:00Z")

        flattened = bot._flatten_account_runtime_fields({"realAccount": snapshot}, {})
        self.assertEqual(flattened["realWalletBalance"], 100)
        self.assertEqual(flattened["realRealizedPnlToday"], 3.0)
        self.assertEqual(flattened["realTotalPnlToday"], 4.5)
        self.assertEqual(flattened["realMarginRatio"], 5.88)

    @patch.object(KucoinTradeClient, "credentials_present", return_value=True)
    def test_bot_manager_daily_failure_is_null_not_zero(self, _credentials):
        client = Mock()
        client.get_account_overview.return_value = {
            "accountType": "KUCOIN_FUTURES", "permission": "READ_ONLY",
            "balance": 101.5, "equity": 101.5, "availableBalance": 90,
            "walletBalance": 100, "unrealizedPnl": 1.5, "marginRatio": 0,
        }
        client.get_realized_pnl_today.side_effect = RuntimeError("ledger unavailable")
        client.get_positions.return_value = []
        bot = BotManager()
        bot.account_read_client = client
        bot.account_read_client_exchange = "kucoin"

        snapshot = bot._refresh_real_account_snapshot("kucoin")
        self.assertIsNone(snapshot["realizedPnlToday"])
        self.assertIsNone(snapshot["totalPnlToday"])
        self.assertEqual(snapshot["marginRatio"], 0)

    def test_total_pnl_requires_both_authoritative_operands(self):
        self.assertEqual(account_status_total_pnl_today(3, 2), 5.0)
        self.assertEqual(account_status_total_pnl_today(3, -1.25), 1.75)
        self.assertEqual(account_status_total_pnl_today(-3, 5), 2.0)
        self.assertEqual(account_status_total_pnl_today(0, 0), 0.0)
        self.assertIsNone(account_status_total_pnl_today(None, 1))
        self.assertIsNone(account_status_total_pnl_today(1, None))
        self.assertIsNone(account_status_total_pnl_today("bad", 1))


if __name__ == "__main__":
    unittest.main()
