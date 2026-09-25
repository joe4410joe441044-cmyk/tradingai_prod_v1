"""PAPER/REAL_LIVE equity-authority separation for the MM high-water mark.

Production incident (WORK-AA E2E-003): the persisted REAL_LIVE loss state had
a validated peak of 7.91836966.  A backend restart while the bot was STOPPED
in PAPER ran stopped-PAPER maintenance, which folded the PAPER account equity
10000 into that REAL_LIVE peak without changing the authority marker.  The
next LIVE START saw no authority transition and locked on a fictitious
99.92% drawdown.

Invariant: an equity observation may update a high-water mark only when it
belongs to the same equity authority.
"""

import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetricsState,
)
from backend.money_management.loss_persistence_models import (
    AccountingRebaseAuthoritySource,
    PersistedDrawdownState,
)
from backend.money_management.loss_runtime_integration_models import StateSource
from backend.runtime.governance_runtime import governance_state
from backend.runtime.paper_account_store import PaperAccountStore
from tests.test_money_management_period_rollover_authority import (
    CUR_DAY,
    _state_at,
)


D = Decimal
PAPER = AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY
LIVE = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY
LIVE_PEAK = D("7.91836966")
PAPER_EQUITY = D("10000")


def state_with(authority, peak, equity, at=CUR_DAY):
    state = _state_at(at, starting_equity=equity)
    amount = peak - equity
    return replace(
        state,
        drawdown_state=PersistedDrawdownState(
            peak, equity, amount, amount / peak * D("100"), at
        ),
        accounting_authority_source=authority,
    )


def restored(authority, peak, equity, runtime="runtime-1"):
    metrics = AuthoritativeLossRuntimeMetricsState(runtime)
    metrics.restore(
        state_with(authority, peak, equity),
        StateSource.PERSISTED_STATE,
        CUR_DAY + timedelta(seconds=1),
        preserve_periods=True,
    )
    return metrics


def maintenance(metrics, equity, seconds=5):
    return metrics.observe_stopped_paper_maintenance(
        as_of=CUR_DAY + timedelta(seconds=seconds),
        session_id=0,
        balance=equity,
        equity=equity,
        available_balance=equity,
        realized_pnl=D("0"),
        unrealized_pnl=D("0"),
        position=None,
        mark_price=None,
    )


def observe(metrics, equity, authority, source_state="RUNNING", seconds=10,
            session_id=0):
    return metrics.observe(
        as_of=CUR_DAY + timedelta(seconds=seconds),
        session_id=session_id,
        balance=equity,
        equity=equity,
        available_balance=equity,
        realized_pnl=D("0"),
        unrealized_pnl=D("0"),
        position=None,
        mark_price=None,
        accounting_authority_source=authority.value,
        source_state=source_state,
    )


class StoppedPaperMaintenanceAuthorityTests(unittest.TestCase):
    """Phase-4 reproduction and matrix items 1-4, 12 (metrics accumulator)."""

    def test_live_peak_survives_stopped_paper_maintenance(self):
        # Matrix 1 / reproduction: LIVE 7.918 + PAPER maintenance 10000.
        metrics = restored(LIVE, LIVE_PEAK, LIVE_PEAK)
        try:
            maintenance(metrics, PAPER_EQUITY)
        except ValueError:
            pass
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.peak_equity, LIVE_PEAK)
        self.assertIs(snapshot.accounting_authority_source, LIVE)

    def test_paper_peak_rises_with_higher_paper_maintenance_equity(self):
        # Matrix 2: PAPER maintenance keeps its existing PAPER peak semantics.
        metrics = restored(PAPER, D("1100"), D("1000"))
        snapshot = maintenance(metrics, D("1200"))
        self.assertEqual(snapshot.peak_equity, D("1200"))
        self.assertIs(snapshot.accounting_authority_source, PAPER)
        self.assertEqual(snapshot.source_state, "STOPPED_PAPER_MAINTENANCE")

    def test_live_peak_rises_with_higher_live_equity(self):
        # Matrix 3.
        metrics = restored(LIVE, LIVE_PEAK, LIVE_PEAK)
        snapshot = observe(metrics, D("8.5"), LIVE)
        self.assertEqual(snapshot.peak_equity, D("8.5"))
        self.assertEqual(snapshot.current_drawdown_pct, D("0"))
        self.assertIs(snapshot.accounting_authority_source, LIVE)

    def test_lower_live_equity_is_a_normal_drawdown(self):
        # Matrix 4.
        metrics = restored(LIVE, LIVE_PEAK, LIVE_PEAK)
        snapshot = observe(metrics, D("7.5"), LIVE)
        self.assertEqual(snapshot.peak_equity, LIVE_PEAK)
        self.assertEqual(snapshot.current_drawdown_amount, LIVE_PEAK - D("7.5"))
        self.assertEqual(
            snapshot.current_drawdown_pct,
            (LIVE_PEAK - D("7.5")) / LIVE_PEAK * D("100"),
        )

    def test_non_transition_paper_observation_cannot_lift_live_peak(self):
        # Invariant C: a PAPER observation that cannot establish a validated
        # authority transition (not RUNNING) never raises a REAL_LIVE peak.
        metrics = restored(LIVE, LIVE_PEAK, LIVE_PEAK)
        snapshot = observe(metrics, PAPER_EQUITY, PAPER, source_state="STOPPED")
        self.assertEqual(snapshot.peak_equity, LIVE_PEAK)
        self.assertIs(snapshot.accounting_authority_source, LIVE)

    def test_non_transition_live_observation_cannot_lift_paper_peak(self):
        metrics = restored(PAPER, D("1000"), D("1000"))
        snapshot = observe(metrics, D("5000"), LIVE, source_state="STOPPED")
        self.assertEqual(snapshot.peak_equity, D("1000"))
        self.assertIs(snapshot.accounting_authority_source, PAPER)

    def test_running_authority_transition_still_rebases_to_new_authority(self):
        # Existing validated transition semantics remain unchanged.
        metrics = restored(PAPER, D("10000"), D("10000"))
        snapshot = observe(metrics, LIVE_PEAK, LIVE)
        self.assertEqual(snapshot.peak_equity, LIVE_PEAK)
        self.assertIs(snapshot.accounting_authority_source, LIVE)

    def test_repeated_maintenance_never_recontaminates(self):
        # Matrix 12 (accumulator level).
        metrics = restored(LIVE, LIVE_PEAK, LIVE_PEAK)
        for seconds, equity in ((5, PAPER_EQUITY), (6, D("20000"))):
            with self.assertRaises(ValueError):
                maintenance(metrics, equity, seconds=seconds)
        self.assertEqual(metrics.snapshot().peak_equity, LIVE_PEAK)


class BotManagerStoppedPaperRestoreTests(unittest.TestCase):
    """The production restore path used by the startup runtime hook."""

    def setUp(self):
        self.governance = deepcopy(governance_state)
        governance_state.update({"mode": "PAPER", "execution_enabled": False})
        self.temp = TemporaryDirectory()
        self.manager = BotManager()
        self.manager.config = {"mode": "paper"}
        self.store = PaperAccountStore(
            f"{self.temp.name}/paper.json", account_scope="primary"
        )
        self.manager.paper_account_store = self.store
        from datetime import datetime, timezone
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.manager.paper_account_state = self.store.build_state(
            PAPER_EQUITY, "PAPER_SIMULATION", self.now.timestamp()
        )
        self.manager.paper_account_runtime_snapshot = (
            self.store.as_runtime_snapshot(self.manager.paper_account_state)
        )

    def tearDown(self):
        governance_state.clear()
        governance_state.update(self.governance)
        self.temp.cleanup()

    def initialize(self, authority, peak, equity):
        return self.manager.initialize_money_management_runtime_metrics(
            state_with(authority, peak, equity, at=self.now),
            StateSource.PERSISTED_STATE,
            self.now,
        )

    def test_restart_while_stopped_paper_keeps_real_live_peak(self):
        # Exact incident path: persisted REAL_LIVE peak 7.918, paper 10000.
        metrics = self.initialize(LIVE, LIVE_PEAK, LIVE_PEAK)
        self.assertEqual(metrics.peak_equity, LIVE_PEAK)
        self.assertIs(metrics.accounting_authority_source, LIVE)
        self.assertEqual(
            self.manager.money_management_runtime_metrics.snapshot().peak_equity,
            LIVE_PEAK,
        )

    def test_restart_while_stopped_paper_still_maintains_paper_state(self):
        metrics = self.initialize(PAPER, D("9000"), D("9000"))
        self.assertIs(metrics.accounting_authority_source, PAPER)
        self.assertLessEqual(metrics.peak_equity, PAPER_EQUITY)
        self.assertGreaterEqual(metrics.peak_equity, D("9000"))


if __name__ == "__main__":
    unittest.main()
