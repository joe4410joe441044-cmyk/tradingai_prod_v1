import unittest
from unittest.mock import patch

from backend.api.bot_api import StatusResponse
from backend.bot_manager.bot_manager import BotManager
from backend.execution.kucoin_trade import KucoinTradeClient


class FakeEngine:
    balance = 4321.25
    pnl = 12.5
    unrealized_pnl = -2.25
    actual_position = {
        "symbol": "BTCUSDT",
        "side": "BUY",
    }
    pending_order = False


class FakeReadOnlyEngine:
    balance = 9876.54
    pnl = 3.0
    unrealized_pnl = 1.5
    actual_position = {
        "symbol": "XRPUSDTM",
        "side": "BUY",
        "qty": 12,
    }
    pending_order = False
    real_available_balance = 9000.12
    config = {
        "mode": "live",
        "dry_run": True,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 5,
        "sl_percent": 1,
        "tp_percent": 2,
        "timeframe": "1m",
        "leverage": 5,
        "trailing_stop": False,
    }

    def get_risk_state(self):
        return {}

    def build_live_readiness(self):
        return {
            "ready": False,
            "realOrderAllowed": False,
            "checks": {},
            "blockReasons": [
                "LIVE_NOT_ENABLED",
                "TRADE_MODE_NOT_LIVE",
                "DRY_RUN_ACTIVE",
            ],
            "selectedMode": "LIVE",
            "dryRun": True,
            "tradeMode": "paper",
            "allowLive": False,
            "exchangeClientReady": True,
            "exchangeAuthReady": True,
            "balanceCheckOk": True,
            "positionCheckOk": True,
            "executionEnabled": False,
            "emergencyStop": False,
            "realBalance": self.balance,
            "realEquity": self.balance + self.unrealized_pnl,
            "realAvailableBalance": self.real_available_balance,
            "realPosition": self.actual_position,
            "realPositionState": "OPEN",
            "realAccountLastSync": 1234567890.0,
            "exchangeConnection": "CONNECTED",
            "apiKeyStatus": "VERIFIED",
            "permission": "READ_ONLY",
            "accountType": "KUCOIN_FUTURES",
            "exchangeAuthReason": "KUCOIN_CREDENTIALS_VERIFIED",
            "exchangeConnectionReason": "KUCOIN_CLIENT_READY",
            "accountReason": "KUCOIN_READ_ONLY_SYNC_OK",
            "balanceReason": "KUCOIN_BALANCE_SYNC_OK",
            "positionReason": "KUCOIN_POSITION_SYNC_OK",
            "accountSnapshot": {},
        }


class ExchangeLiveStatusTest(unittest.TestCase):

    def test_account_values_remain_available_after_stop(self):
        bot = BotManager()
        bot.engine = FakeEngine()
        bot._running = True

        running = bot.get_status()
        bot.stop()
        stopped = bot.get_status()

        self.assertEqual(stopped["status"], "STOPPED")
        self.assertEqual(stopped["balance"], running["balance"])
        self.assertEqual(stopped["balance"], 4321.25)
        self.assertEqual(stopped["equity"], running["equity"])
        self.assertEqual(stopped["equity"], 4319.0)
        self.assertEqual(stopped["pnl"], running["pnl"])
        self.assertEqual(stopped["pnl"], 10.25)
        self.assertEqual(stopped["position"], running["position"])
        self.assertGreaterEqual(
            stopped["last_update"],
            running["last_update"],
        )
        self.assertFalse(stopped["ws_connected"])

        # FastAPI must retain the fields consumed by CENTER 1.
        response = StatusResponse(**stopped)
        self.assertEqual(response.last_update, stopped["last_update"])

    def test_status_labels_paper_values_and_real_account_safety(self):
        bot = BotManager()
        bot.config = {"mode": "live"}

        status = bot.get_status()
        response = StatusResponse(**status)

        self.assertEqual(response.accountSource, "PAPER_SIMULATION")
        self.assertEqual(response.balanceSource, "PAPER_SIMULATION")
        self.assertEqual(response.positionSource, "PAPER_SIMULATION")
        self.assertEqual(response.selectedMode, "LIVE")
        self.assertEqual(response.executionMode, "SIMULATION")
        self.assertTrue(response.dryRun)
        self.assertFalse(response.realOrderAllowed)
        self.assertFalse(response.realAccountConnected)
        self.assertEqual(response.exchangeAuth, "NOT_VERIFIED")
        self.assertIsNone(response.realBalance)
        self.assertIsNone(response.realPosition)
        self.assertEqual(
            response.safetyReason,
            "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE",
        )
        self.assertFalse(status["real_order_allowed"])
        self.assertEqual(status["execution_mode"], "SIMULATION")

    def test_live_read_only_account_fields_reach_status_and_runtime_debug(self):
        bot = BotManager()
        bot.engine = FakeReadOnlyEngine()
        bot.config = dict(FakeReadOnlyEngine.config)
        bot.symbol = "XRPUSDT"
        bot.exchange_name = "kucoin"
        bot.orderbook_source = "kucoin_futures"
        bot.orderbook_symbol = "XRPUSDTM"
        bot._running = True
        bot.latest_runtime_result = {"runtimeDebug": {}}

        status = bot.get_status()
        response = StatusResponse(**status)
        runtime_debug = status["latestRuntimeResult"]["runtimeDebug"]

        self.assertEqual(response.selectedMode, "LIVE")
        self.assertEqual(response.executionMode, "SIMULATION")
        self.assertTrue(response.dryRun)
        self.assertFalse(response.realOrderAllowed)
        self.assertFalse(status["real_order_allowed"])
        self.assertEqual(response.accountSource, "KUCOIN_FUTURES_READ_ONLY")
        self.assertEqual(response.balanceSource, "KUCOIN_FUTURES_READ_ONLY")
        self.assertEqual(response.positionSource, "KUCOIN_FUTURES_READ_ONLY")
        self.assertTrue(response.realAccountConnected)
        self.assertEqual(response.exchangeAuth, "VERIFIED")
        self.assertEqual(response.exchangeConnection, "CONNECTED")
        self.assertEqual(response.apiKeyStatus, "VERIFIED")
        self.assertEqual(response.permission, "READ_ONLY")
        self.assertEqual(response.accountType, "KUCOIN_FUTURES")
        self.assertEqual(response.realBalance, 9876.54)
        self.assertEqual(response.realEquity, 9878.04)
        self.assertEqual(response.realAvailableBalance, 9000.12)
        self.assertEqual(response.realPosition, FakeReadOnlyEngine.actual_position)
        self.assertEqual(response.realPositionState, "OPEN")
        self.assertEqual(response.realLastSync, 1234567890.0)
        self.assertEqual(response.balanceReason, "KUCOIN_BALANCE_SYNC_OK")
        self.assertEqual(response.positionReason, "KUCOIN_POSITION_SYNC_OK")
        self.assertEqual(
            response.accountRuntime["realAccount"]["balance"],
            9876.54,
        )
        self.assertEqual(
            response.accountRuntime["paperAccount"]["source"],
            "PAPER_SIMULATION",
        )

        for key in [
            "accountSource",
            "balanceSource",
            "positionSource",
            "realBalance",
            "realEquity",
            "realAvailableBalance",
            "realPosition",
            "exchangeAuth",
            "exchangeConnection",
            "apiKeyStatus",
            "permission",
            "accountType",
            "realOrderAllowed",
            "dryRun",
            "tradeMode",
        ]:
            self.assertEqual(runtime_debug[key], status[key])

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_account_overview_uses_read_only_get(self, request_get):
        request_get.return_value.json.return_value = {
            "code": "200000",
            "data": {
                "currency": "USDT",
                "accountEquity": "123.45",
                "availableBalance": "120.00",
                "marginBalance": "122.00",
                "unrealisedPNL": "1.45",
            },
        }
        client = KucoinTradeClient(
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )

        overview = client.get_account_overview()

        self.assertEqual(overview["source"], "KUCOIN_FUTURES_READ_ONLY")
        self.assertEqual(overview["balance"], 123.45)
        self.assertEqual(overview["equity"], 123.45)
        self.assertEqual(overview["availableBalance"], 120.0)
        self.assertEqual(overview["permission"], "READ_ONLY")
        self.assertEqual(request_get.call_count, 1)
        self.assertIn(
            "/api/v1/account-overview?currency=USDT",
            request_get.call_args.args[0],
        )

    def test_paper_mode_fetches_kucoin_real_account_read_only(self):
        bot = BotManager()
        bot.engine = FakeEngine()
        bot.config = {
            "mode": "paper",
            "dry_run": True,
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
        }
        bot.symbol = "XRPUSDT"
        bot.exchange_name = "kucoin"
        bot.orderbook_symbol = "XRPUSDTM"
        bot._running = True

        with patch(
            "backend.bot_manager.bot_manager.KucoinTradeClient"
        ) as client_class:
            client_class.credentials_present.return_value = True
            client = client_class.return_value
            client.get_account_overview.return_value = {
                "source": "KUCOIN_FUTURES_READ_ONLY",
                "accountType": "KUCOIN_FUTURES",
                "balance": 222.0,
                "equity": 225.5,
                "availableBalance": 200.25,
                "permission": "READ_ONLY",
            }
            client.get_positions.return_value = None

            status = bot.get_status()
            cached = bot.get_status()

        response = StatusResponse(**status)
        account_runtime = response.accountRuntime

        self.assertEqual(response.selectedMode, "PAPER")
        self.assertEqual(response.executionMode, "SIMULATION")
        self.assertFalse(response.realOrderAllowed)
        self.assertTrue(response.dryRun)
        self.assertEqual(response.balance, 4321.25)
        self.assertEqual(
            account_runtime["paperAccount"]["balance"],
            4321.25,
        )
        self.assertEqual(
            account_runtime["paperAccount"]["source"],
            "PAPER_SIMULATION",
        )
        self.assertEqual(
            account_runtime["realAccount"]["exchange"],
            "kucoin",
        )
        self.assertEqual(
            account_runtime["realAccount"]["balance"],
            222.0,
        )
        self.assertEqual(
            account_runtime["realAccount"]["availableBalance"],
            200.25,
        )
        self.assertEqual(
            account_runtime["realAccount"]["positions"],
            [],
        )
        self.assertEqual(
            account_runtime["realAccount"]["positionSummary"],
            "NO_OPEN_POSITION",
        )
        self.assertEqual(
            response.balanceSource,
            "KUCOIN_FUTURES_READ_ONLY",
        )
        self.assertEqual(
            response.realPosition,
            [],
        )
        self.assertEqual(
            client.get_account_overview.call_count,
            1,
        )
        self.assertEqual(
            client.get_positions.call_count,
            1,
        )
        self.assertEqual(
            cached["accountRuntime"]["realAccount"]["generation"],
            status["accountRuntime"]["realAccount"]["generation"],
        )


if __name__ == "__main__":
    unittest.main()
