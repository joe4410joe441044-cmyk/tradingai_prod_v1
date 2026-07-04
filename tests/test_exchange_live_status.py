import unittest

from backend.api.bot_api import StatusResponse
from backend.bot_manager.bot_manager import BotManager


class FakeEngine:
    balance = 4321.25
    pnl = 12.5
    unrealized_pnl = -2.25
    actual_position = {
        "symbol": "BTCUSDT",
        "side": "BUY",
    }
    pending_order = False


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


if __name__ == "__main__":
    unittest.main()
