import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION, PeriodCode, PersistedCashFlowState,
    PersistedDrawdownState, PersistedLossPeriodState, PersistedLossState,
)
from backend.money_management.loss_reason_models import (
    LossReasonContract, ReasonCode, RecommendedAction,
)
from backend.money_management.enums import RiskState
from backend.money_management.loss_runtime_integration_models import StateSource
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeMetricsReadRequest, LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_metrics_source import (
    BotManagerLossRuntimeMetricsSource,
)
from backend.money_management.loss_runtime_hook import (
    register_money_management_runtime_hook,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType
from backend.runtime.governance_runtime import governance_state
from backend.runtime.paper_account_store import PaperAccountStore
from tests.test_money_management_loss_runtime_hook import (
    application, dispatch_result,
)


D = Decimal


def persisted(now, pnl=(D("-4"), D("-5"), D("-6")), scope="primary"):
    periods = []
    for code, kind, value in zip(PeriodCode, PeriodType, pnl):
        item = period_for(now, kind)
        loss = max(D("0"), -value)
        periods.append(PersistedLossPeriodState(
            code, item.period_key, item.start_at, item.end_at, D("1000"),
            value, loss, loss / D("1000") * D("100"), D("0"), now,
        ))
    decision = LossReasonContract(
        "money-management-loss-reason/v1", now, RiskState.NORMAL,
        RecommendedAction.CONTINUE, ReasonCode.NONE,
        (), (), (), (), (), (), False,
    )
    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION, scope, "USDT", *periods,
        PersistedDrawdownState(D("1100"), D("1000"), D("100"),
                               D("100") / D("1100") * D("100"), now),
        PersistedCashFlowState(False, (), D("0")), decision, now,
    )


class StoppedPaperRecoveryMetricsTests(unittest.TestCase):
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
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.manager.paper_account_state = self.store.build_state(
            D("1000"), "PAPER_SIMULATION", self.now.timestamp()
        )
        self.manager.paper_account_runtime_snapshot = self.store.as_runtime_snapshot(
            self.manager.paper_account_state
        )

    def tearDown(self):
        governance_state.clear()
        governance_state.update(self.governance)
        self.temp.cleanup()

    def initialize(self, state=None):
        state = state or persisted(self.now)
        return self.manager.initialize_money_management_runtime_metrics(
            state, StateSource.PERSISTED_STATE, self.now
        )

    def read(self, age=90):
        source = BotManagerLossRuntimeMetricsSource(
            self.manager, timestamp_source=lambda: self.now
        )
        return source.read_metrics(LossRuntimeMetricsReadRequest(
            "test", self.now, timedelta(seconds=age)
        ))

    def test_fresh_stopped_paper_is_available_complete_and_current_identity(self):
        metrics = self.initialize()
        result = self.read()
        self.assertTrue(metrics.is_complete)
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.AVAILABLE)
        self.assertEqual(result.metrics.runtime_instance_id,
                         self.manager.runtime_instance_id)
        self.assertFalse(governance_state["execution_enabled"])

    def test_restored_period_values_are_preserved(self):
        self.initialize()
        raw = self.manager.get_runtime_metrics_snapshot()
        self.assertEqual((raw["dailyPnL"], raw["weeklyPnL"], raw["monthlyPnL"]),
                         (D("-4"), D("-5"), D("-6")))

    def test_missing_and_invalid_equity_fail_closed(self):
        for value in (None, "invalid"):
            with self.subTest(value=value):
                manager = BotManager()
                manager.config = {"mode": "paper"}
                manager.paper_account_store = self.store
                manager.paper_account_state = dict(self.manager.paper_account_state,
                                                   equity=value)
                manager.paper_account_runtime_snapshot = self.store.as_runtime_snapshot(
                    self.manager.paper_account_state
                )
                manager.initialize_money_management_runtime_metrics(
                    persisted(self.now), StateSource.PERSISTED_STATE, self.now
                )
                result = BotManagerLossRuntimeMetricsSource(
                    manager, timestamp_source=lambda: self.now
                ).read_metrics(LossRuntimeMetricsReadRequest(
                    "test", self.now, timedelta(seconds=90)
                ))
                self.assertIn(result.status, {
                    LossRuntimeMetricsReadStatus.UNAVAILABLE,
                    LossRuntimeMetricsReadStatus.INCONSISTENT,
                })

    def test_stale_store_reports_stale(self):
        self.manager.paper_account_state["updatedAt"] = (
            self.now - timedelta(seconds=91)
        ).timestamp()
        self.initialize()
        self.assertEqual(self.read().status, LossRuntimeMetricsReadStatus.STALE)

    def test_unknown_pnl_and_trade_counts_are_not_coerced(self):
        state = persisted(self.now)
        self.manager.paper_account_state["realizedPnl"] = None
        self.initialize(state)
        raw = self.manager.get_runtime_metrics_snapshot()
        self.assertIsNone(raw["realizedPnL"])
        self.assertIsNone(raw["tradeCountDaily"])
        self.assertIsNone(raw["tradeCountWeekly"])
        self.assertIsNone(raw["tradeCountMonthly"])

    def test_live_engine_and_execution_enabled_refuse_maintenance(self):
        cases = ("live", "engine", "execution")
        for case in cases:
            with self.subTest(case=case):
                manager = BotManager()
                manager.paper_account_store = self.store
                manager.paper_account_state = deepcopy(self.manager.paper_account_state)
                manager.paper_account_runtime_snapshot = self.store.as_runtime_snapshot(
                    manager.paper_account_state
                )
                manager.config = {"mode": "live" if case == "live" else "paper"}
                if case == "engine":
                    manager.engine = object()
                governance_state["execution_enabled"] = case == "execution"
                result = manager.initialize_money_management_runtime_metrics(
                    persisted(self.now), StateSource.PERSISTED_STATE, self.now
                )
                self.assertNotEqual(result.source_state,
                                    "STOPPED_PAPER_MAINTENANCE")
                governance_state["execution_enabled"] = False

    def test_position_and_pending_are_reflected(self):
        position = {"side": "BUY", "coin_qty": 2, "markPrice": 10,
                    "entryPrice": 9, "stopLoss": 8}
        self.manager.paper_account_state.update({
            "position": position, "positions": [position],
            "positionState": "OPEN", "pendingOrder": True,
        })
        metrics = self.initialize()
        raw = self.manager.get_runtime_metrics_snapshot()
        self.assertEqual(metrics.position_count, 1)
        self.assertEqual(raw["pendingOrderCount"], 1)
        self.assertFalse(governance_state["execution_enabled"])

    def test_scope_mismatch_and_period_mismatch_fail_closed(self):
        result = self.initialize(persisted(self.now, scope="other"))
        self.assertNotEqual(result.source_state, "STOPPED_PAPER_MAINTENANCE")
        old = self.now - timedelta(days=40)
        manager = BotManager()
        manager.config = {"mode": "paper"}
        manager.paper_account_store = self.store
        manager.paper_account_state = deepcopy(self.manager.paper_account_state)
        manager.paper_account_runtime_snapshot = self.store.as_runtime_snapshot(
            manager.paper_account_state
        )
        mismatch = manager.initialize_money_management_runtime_metrics(
            persisted(old), StateSource.PERSISTED_STATE, self.now
        )
        self.assertNotEqual(mismatch.source_state,
                            "STOPPED_PAPER_MAINTENANCE")
        self.assertEqual(mismatch.daily_realized_pnl, D("-4"))

    def test_startup_dispatch_uses_formal_hook_once(self):
        class MaintenanceBot:
            def __init__(self):
                self.callbacks = []

            def get_runtime_metrics_snapshot(self):
                return {
                    "sourceState": "STOPPED_PAPER_MAINTENANCE",
                    "runtimeInstanceId": "current-runtime",
                    "metricsRevision": 2,
                }

            def set_money_management_runtime_hook(self, callback):
                self.callbacks.append(callback)
                return True

        bot = MaintenanceBot()
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            return_value=dispatch_result(LossRuntimeDispatchStatus.APPLIED),
        ) as dispatch:
            registration = register_money_management_runtime_hook(
                application(), lambda: bot, timestamp_source=lambda: self.now
            )
        self.assertIsNotNone(registration)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(registration.hook.last_dispatch_status,
                         LossRuntimeDispatchStatus.APPLIED)


if __name__ == "__main__":
    unittest.main()
