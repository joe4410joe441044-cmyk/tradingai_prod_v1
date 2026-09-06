"""Targeted tests: PAPER account -> MM capital authority mode-gating.

Confirms the MM capital authority is mode-aware so PAPER sizing uses the
canonical PAPER account (SET PAPER CAPITAL) instead of REAL_LIVE_ACCOUNT,
without hard-coding 100 and without any live fallback.
"""

from decimal import Decimal
import time
import unittest

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.money_management.paper_capital_authority import (
    build_paper_capital_eligibility,
)


def paper_state(balance):
    """Build a canonical PAPER account state the store would hold."""
    value = Decimal(str(balance))
    return {
        "schemaVersion": 1,
        "capital": format(value, ".2f"),
        "balance": format(value, ".2f"),
        "equity": format(value, ".2f"),
        "availableBalance": format(value, ".2f"),
        "realizedPnl": "0.00",
        "unrealizedPnl": "0.00",
        "totalPnl": "0.00",
        "position": None,
        "positions": [],
        "positionState": "FLAT",
        "pendingOrder": False,
        "updatedAt": time.time(),
        "source": "DASHBOARD_MANUAL",
    }


class PaperCapitalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.config = build_default_money_management_config()

    def test_paper_capital_authority_is_used_for_mm(self):
        capital = build_paper_capital_eligibility(
            paper_state("100"),
            config=self.config,
            policy_version="money-management-config/v1",
        )
        self.assertEqual(capital.available_capital, Decimal("100"))
        self.assertEqual(capital.equity, Decimal("100"))
        self.assertEqual(capital.input_authority, "PAPER_ACCOUNT")
        self.assertEqual(capital.capital_source, "PAPER_ACCOUNT")

    def test_paper_capital_propagates_dynamically_not_hardcoded_100(self):
        capital = build_paper_capital_eligibility(
            paper_state("250"),
            config=self.config,
            policy_version="money-management-config/v1",
        )
        self.assertEqual(capital.available_capital, Decimal("250"))
        self.assertEqual(capital.equity, Decimal("250"))

    def test_paper_capital_authority_fails_closed_on_missing_balance(self):
        state = paper_state("100")
        state["balance"] = None
        state["equity"] = None
        state["availableBalance"] = None
        with self.assertRaises(RuntimeError):
            build_paper_capital_eligibility(
                state,
                config=self.config,
                policy_version="money-management-config/v1",
            )

    def test_paper_capital_authority_fails_closed_on_restore_reason(self):
        state = paper_state("100")
        state["restoreReason"] = "PAPER_ACCOUNT_STATE_CORRUPT"
        with self.assertRaises(RuntimeError):
            build_paper_capital_eligibility(
                state,
                config=self.config,
                policy_version="money-management-config/v1",
            )


class PaperAuthorityModeGateTests(unittest.TestCase):
    def _manager(self, *, mode, paper_state_value=None, restore_reason=None):
        manager = BotManager.__new__(BotManager)
        manager.config = {"mode": mode}
        state = paper_state("100")
        if paper_state_value is not None:
            state = paper_state(paper_state_value)
        if restore_reason:
            state["restoreReason"] = restore_reason
        manager.paper_account_state = state
        manager.production_ams_mm_config_provider = (
            lambda: build_default_money_management_config()
        )
        return manager

    def test_paper_mode_uses_paper_account_not_live_refresh(self):
        manager = self._manager(mode="paper", paper_state_value="100")
        refreshed = []
        manager.refresh_production_ams_read_model = lambda **kwargs: refreshed.append(
            kwargs
        ) or {"capitalEligibilityContract": None}
        capital = manager.get_official_mm_capital_authority()
        self.assertIsNotNone(capital)
        self.assertEqual(capital.available_capital, Decimal("100"))
        self.assertEqual(capital.input_authority, "PAPER_ACCOUNT")
        self.assertEqual(refreshed, [])

    def test_paper_mode_propagates_dynamic_capital(self):
        manager = self._manager(mode="paper", paper_state_value="250")
        capital = manager.get_official_mm_capital_authority()
        self.assertIsNotNone(capital)
        self.assertEqual(capital.available_capital, Decimal("250"))

    def test_paper_mode_fails_closed_without_live_fallback(self):
        manager = self._manager(mode="paper", restore_reason="PAPER_ACCOUNT_STATE_CORRUPT")
        refreshed = []
        manager.refresh_production_ams_read_model = lambda **kwargs: refreshed.append(
            kwargs
        ) or {"capitalEligibilityContract": None}
        capital = manager.get_official_mm_capital_authority()
        self.assertIsNone(capital)
        self.assertEqual(refreshed, [])

    def test_live_mode_preserves_real_live_authority(self):
        manager = self._manager(mode="live")
        manager.refresh_production_ams_read_model = lambda **kwargs: {
            "capitalEligibilityContract": None,
        }
        capital = manager.get_official_mm_capital_authority()
        self.assertIsNone(capital)


if __name__ == "__main__":
    unittest.main()
