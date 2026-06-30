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


if __name__ == "__main__":
    unittest.main()
