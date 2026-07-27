import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.money_management.enums import RiskState
from backend.money_management.loss_decision import evaluate_loss_decision
from backend.money_management.loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION,
    FreshnessStatus,
    PeriodCode,
    PersistedCashFlowState,
    PersistedDrawdownState,
    PersistedLossPeriodState,
    PersistedLossState,
)
from backend.money_management.loss_reason_models import (
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
    build_reason_contract,
)
from backend.money_management.loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
    LossRuntimeEvaluationStatus,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    RuntimeLifecycle,
    StateSource,
)
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetrics,
)
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType


D = Decimal
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def reason(at=NOW):
    return LossReasonContract(
        "money-management-loss-reason/v1",
        at,
        RiskState.NORMAL,
        RecommendedAction.CONTINUE,
        ReasonCode.NONE,
        (),
        (),
        (),
        (),
        (),
        (),
        False,
    )


def period(code, typ, at=NOW, pnl=D("0")):
    current = period_for(at, typ)
    loss = max(D("0"), -pnl)
    return PersistedLossPeriodState(
        code,
        current.period_key,
        current.start_at,
        current.end_at,
        D("1000"),
        pnl,
        loss,
        loss / D("1000") * D("100"),
        D("0"),
        at,
    )


def state(at=NOW):
    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION,
        "primary",
        "USDT",
        period(PeriodCode.DAILY, PeriodType.DAILY, at),
        period(PeriodCode.WEEKLY, PeriodType.WEEKLY, at),
        period(PeriodCode.MONTHLY, PeriodType.MONTHLY, at),
        PersistedDrawdownState(D("1000"), D("1000"), D("0"), D("0"), at),
        PersistedCashFlowState(False, (), D("0")),
        reason(at),
        at,
        freshness=FreshnessStatus.VALID,
    )


def snapshot(current=None, at=NOW):
    return LossLimitRuntimeSnapshot(
        RuntimeLifecycle.READY,
        current if current is not None else state(at),
        StateSource.CURRENT_RUNTIME_STATE,
        GovernanceProjection.CONTINUE,
        LossLimitRecoveryRequirement(False, (), False, False, False, "none"),
        (),
        1,
        1,
        at,
        at,
        "ready",
    )


def metrics(at=NOW + timedelta(minutes=1), **overrides):
    values = {
        "captured_at": at,
        "source_revision": "account:8",
        "equity": D("1000"),
        "balance": D("1000"),
        "available_balance": D("900"),
        "realized_pnl": D("0"),
        "unrealized_pnl": D("0"),
        "daily_pnl": D("0"),
        "weekly_pnl": D("0"),
        "monthly_pnl": D("0"),
        "peak_equity": D("1000"),
        "drawdown": D("0"),
        "open_exposure": D("0"),
        "position_count": 0,
        "trade_count": 0,
        "source_state": "RUNNING",
        "data_quality": LossRuntimeDataQuality.COMPLETE,
    }
    values.update(overrides)
    return LossRuntimeMetrics(**values)


class EvaluationBridgeTests(unittest.TestCase):
    def test_existing_domain_services_are_called_and_context_is_complete(self):
        calls = []

        def evaluator(value):
            calls.append(("evaluate", value))
            return evaluate_loss_decision(value)

        def builder(value):
            calls.append(("reason", value))
            return build_reason_contract(value)

        before_metrics = metrics().to_dict()
        before_state = state().to_dict()
        result = LossRuntimeEvaluationBridge(
            domain_evaluator=evaluator, reason_builder=builder
        ).evaluate(metrics(), snapshot(), "bot:8:EQUITY_UPDATE")
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        self.assertEqual([item[0] for item in calls], ["evaluate", "reason"])
        self.assertEqual(
            result.build_context.governance_projection,
            GovernanceProjection.CONTINUE,
        )
        self.assertEqual(metrics().to_dict(), before_metrics)
        self.assertEqual(state().to_dict(), before_state)

    def test_domain_thresholds_are_reused_for_block(self):
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics(
                equity=D("950"),
                balance=D("950"),
                daily_pnl=D("-20"),
                weekly_pnl=D("-20"),
                monthly_pnl=D("-20"),
                peak_equity=D("1000"),
                drawdown=D("5"),
            ),
            snapshot(),
            "bot:8:EQUITY_UPDATE",
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        self.assertEqual(result.build_context.next_state.risk_state, RiskState.LOCKED)
        self.assertEqual(
            result.build_context.governance_projection,
            GovernanceProjection.BLOCK_EXECUTION,
        )

    def test_determinism(self):
        bridge = LossRuntimeEvaluationBridge()
        first = bridge.evaluate(metrics(), snapshot(), "bot:8:EQUITY_UPDATE")
        second = bridge.evaluate(metrics(), snapshot(), "bot:8:EQUITY_UPDATE")
        self.assertEqual(
            first.build_context.to_dict(), second.build_context.to_dict()
        )

    def test_partial_metrics_fail_before_domain_evaluation(self):
        calls = []
        bridge = LossRuntimeEvaluationBridge(
            domain_evaluator=lambda value: calls.append(value)
        )
        result = bridge.evaluate(
            metrics(data_quality=LossRuntimeDataQuality.PARTIAL),
            snapshot(),
            "bot:8:EQUITY_UPDATE",
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.FAILED)
        self.assertEqual(calls, [])

    def test_missing_runtime_state_and_rollover_require_recovery(self):
        no_state = snapshot()
        object.__setattr__(no_state, "state", None)
        unavailable = LossRuntimeEvaluationBridge().evaluate(
            metrics(), no_state, "bot:8:EQUITY_UPDATE"
        )
        rollover = LossRuntimeEvaluationBridge().evaluate(
            metrics(at=datetime(2026, 7, 27, 0, tzinfo=timezone.utc)),
            snapshot(),
            "bot:9:EQUITY_UPDATE",
        )
        self.assertEqual(
            unavailable.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
        )
        self.assertEqual(
            rollover.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
        )

    def test_evaluation_exception_is_sanitized(self):
        def explode(_):
            raise RuntimeError("secret /tmp/private")

        result = LossRuntimeEvaluationBridge(domain_evaluator=explode).evaluate(
            metrics(), snapshot(), "bot:8:EQUITY_UPDATE"
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.FAILED)
        self.assertNotIn("secret", repr(result))


if __name__ == "__main__":
    unittest.main()
