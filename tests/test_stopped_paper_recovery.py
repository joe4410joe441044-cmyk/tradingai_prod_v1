import json
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.bot_manager.bot_manager import BotManager
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)


class StoppedPaperRecoveryTest(unittest.TestCase):
    def setUp(self):
        self._state_before = dict(governance_state)

    def tearDown(self):
        governance_state.clear()
        governance_state.update(self._state_before)

    @staticmethod
    def _set_governance(execution_enabled=False, emergency_stop=False):
        governance_state["execution_enabled"] = execution_enabled
        governance_state["emergency_stop"] = emergency_stop
        governance_state["emergency_state"] = EMERGENCY_READY
        governance_state["last_emergency_result"] = None
        governance_state["current_emergency_operation_id"] = None
        governance_state["emergency_timeline"] = []

    @staticmethod
    def _recovery_bot():
        bot = BotManager()
        tempdir = tempfile.mkdtemp()
        bot.stopped_paper_durable_snapshot_path = os.path.join(
            tempdir,
            "stopped_paper_safety_snapshot.json",
        )
        return bot

    @staticmethod
    def _paper_backend():
        return (
            patch(
                "backend.bot_manager.bot_manager.backend_config.TRADE_MODE",
                "paper",
            ),
            patch(
                "backend.bot_manager.bot_manager.backend_config.ALLOW_LIVE",
                False,
            ),
        )

    def _recover(self, bot):
        self._set_governance(execution_enabled=False, emergency_stop=False)
        backend_paper, backend_live = self._paper_backend()
        with backend_paper, backend_live:
            result = bot.refresh_stopped_paper_safety_authority()
        return result

    def test_recovery_rebuilds_durable_authority_when_flat(self):
        bot = self._recovery_bot()
        result = self._recover(bot)

        self.assertTrue(result["refreshed"])
        self.assertTrue(result["recovered"])
        self.assertTrue(result["known"])
        self.assertFalse(result["pending"])
        self.assertTrue(result["safe"])

        status = bot.get_stopped_paper_snapshot_status()
        self.assertTrue(status["valid"])
        self.assertTrue(status["durableExists"])
        self.assertFalse(status["stateUnknown"])
        self.assertIsNone(status["reason"])

        pending = bot.get_authoritative_pending_order_state()
        self.assertTrue(pending["known"])
        self.assertFalse(pending["pending"])
        self.assertTrue(pending["safe"])

    def test_recovery_fails_closed_on_position_unknown(self):
        bot = self._recovery_bot()
        bot.position = "OPEN"
        result = self._recover(bot)

        self.assertFalse(result["refreshed"])
        self.assertFalse(result["recovered"])
        self.assertFalse(result["known"])
        self.assertIsNone(result["pending"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["reason"], "POSITION_STATE_UNKNOWN")

        self.assertFalse(
            bot.get_stopped_paper_snapshot_status()["durableExists"]
        )

    def test_recovery_fails_closed_on_pending_unknown(self):
        bot = self._recovery_bot()
        bot.pending_order = None
        result = self._recover(bot)

        self.assertFalse(result["refreshed"])
        self.assertFalse(result["known"])
        self.assertIsNone(result["pending"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["reason"], "PENDING_ORDER_MANAGER_UNKNOWN")
        self.assertFalse(
            bot.get_stopped_paper_snapshot_status()["durableExists"]
        )

    def test_recovery_fails_closed_on_pending_true(self):
        bot = self._recovery_bot()
        bot.pending_order = True
        result = self._recover(bot)

        self.assertFalse(result["refreshed"])
        self.assertFalse(result["known"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["reason"], "PENDING_ORDER_REMAINING")
        self.assertFalse(
            bot.get_stopped_paper_snapshot_status()["durableExists"]
        )

    def test_recovery_fails_closed_on_position_open(self):
        bot = self._recovery_bot()
        bot.account_snapshot = {
            "balance": None,
            "equity": None,
            "availableBalance": None,
            "pnl": None,
            "position": {"symbol": "XRPUSDT", "side": "BUY", "qty": 5},
            "positions": [{"symbol": "XRPUSDT", "side": "BUY", "qty": 5}],
            "realizedPnl": None,
            "unrealizedPnl": None,
            "last_update": None,
            "available": False,
        }
        result = self._recover(bot)

        self.assertFalse(result["refreshed"])
        self.assertFalse(result["known"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["reason"], "POSITION_REMAINING")
        self.assertFalse(
            bot.get_stopped_paper_snapshot_status()["durableExists"]
        )

    def test_recovery_forbidden_in_live_mode(self):
        bot = self._recovery_bot()
        bot.config = {"mode": "live", "dry_run": False}
        governance_state["mode"] = "live"
        backend_paper, backend_live = self._paper_backend()
        with backend_paper, backend_live:
            result = bot.refresh_stopped_paper_safety_authority()

        self.assertFalse(result["refreshed"])
        self.assertFalse(result["known"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["reason"], "LIVE_MODE")
        self.assertFalse(
            bot.get_stopped_paper_snapshot_status()["durableExists"]
        )

    def test_recovery_forbidden_when_emergency_not_ready(self):
        bot = self._recovery_bot()
        governance_state["emergency_stop"] = True
        governance_state["emergency_state"] = "PROCESSING"
        backend_paper, backend_live = self._paper_backend()
        with backend_paper, backend_live:
            result = bot.refresh_stopped_paper_safety_authority()

        self.assertFalse(result["refreshed"])
        self.assertFalse(result["known"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["reason"], "EMERGENCY_NOT_READY")
        self.assertFalse(
            bot.get_stopped_paper_snapshot_status()["durableExists"]
        )

    def test_recovery_recovers_from_unknown_source_stale_snapshot(self):
        bot = self._recovery_bot()
        bot.account_snapshot = {
            "balance": 100.0,
            "equity": 100.0,
            "availableBalance": 100.0,
            "pnl": 0.0,
            "position": None,
            "positions": [],
            "realizedPnl": 0.0,
            "unrealizedPnl": 0.0,
            "last_update": 1_800_000_000.0,
            "available": True,
            "source": "DASHBOARD_MANUAL",
        }
        result = self._recover(bot)

        self.assertTrue(result["refreshed"])
        self.assertTrue(result["recovered"])
        self.assertTrue(result["safe"])
        status = bot.get_stopped_paper_snapshot_status()
        self.assertTrue(status["valid"])
        self.assertTrue(status["durableExists"])
        self.assertFalse(status["stateUnknown"])

    def test_recovery_persists_valid_durable_payload(self):
        bot = self._recovery_bot()
        self._recover(bot)

        path = bot.stopped_paper_durable_snapshot_path
        self.assertTrue(os.path.isfile(path))
        with open(path, "r", encoding="utf-8") as handle:
            durable = json.load(handle)

        self.assertFalse(durable["stateUnknown"])
        self.assertFalse(durable["positionRemaining"])
        self.assertFalse(durable["pendingOrder"])
        self.assertEqual(durable["openOrderCount"], 0)
        self.assertEqual(durable["mode"], "paper")
        self.assertEqual(durable["lifecycleState"], "STOPPED")
        self.assertEqual(
            durable["source"],
            "stopped_paper_recovered_runtime_state",
        )


if __name__ == "__main__":
    unittest.main()
