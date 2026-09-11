"""Focused regression: current STOPPED lifecycle telemetry must not be masked by
stale hook failure history, while the canonical validated authority-rebase
contract and fail-closed behaviour remain intact.
"""

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from backend.money_management.enums import RiskState
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
)
from backend.money_management.loss_governance_projection_dispatcher import (
    LossGovernanceProjectionDispatcher,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceProjectionDispatchStatus,
)
from backend.money_management.loss_persistence_models import (
    AccountingContinuityStatus,
    AccountingRebaseAuditMarker,
    AccountingRebaseAuthoritySource,
    AccountingRebaseAuthorizationState,
    AccountingRebaseReason,
    LossBaselineType,
    PeriodCode,
    PersistedAccountingRebaseRecord,
    PersistedDrawdownState,
    PersistedLossPeriodState,
)
from backend.money_management.loss_reason_models import (
    BlockReason,
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    LossLimitRuntimeStartupDecision,
    RuntimeDecisionStatus,
    RuntimeLifecycle,
    SaveTrigger,
    StateSource,
)
from backend.money_management.loss_runtime_store import (
    LossLimitRuntimeStateStore,
)
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeUpdate,
    StoreFailureCode,
    StoreResultStatus,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType
from tests.test_money_management_loss_governance_projection_dispatcher import (
    NOW,
    Lifecycle,
    application,
    loss_state,
)


D = Decimal
OBSERVED = NOW + timedelta(seconds=30)
PAPER = AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY
LIVE = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY


def _decision(at, state=RiskState.NORMAL, action=RecommendedAction.CONTINUE,
              primary=ReasonCode.NONE, blocks=()):
    return LossReasonContract(
        "money-management-loss-reason/v1", at, state, action, primary,
        (), (), tuple(blocks), (), (), (), False,
    )


def _locked_paper_state():
    locked = _decision(
        NOW, RiskState.LOCKED, RecommendedAction.BLOCK_EXECUTION,
        ReasonCode.DAILY_LOSS_BLOCK, (BlockReason.DAILY_LOSS_BLOCK,),
    )
    return replace(loss_state(), last_decision=locked)


def _rebased_period(code, period_type, observed_at, equity):
    period = period_for(observed_at, period_type)
    return PersistedLossPeriodState(
        code, period.period_key, period.start_at, period.end_at, equity,
        D("0"), D("0"), D("0"), D("0"), observed_at,
        LossBaselineType.ACCOUNTING_REBASE_BASELINE, observed_at,
    )


def _rebase_artifacts(current, observed_at, equity, rebase_id="rebase-1",
                      record_authority=LIVE, next_authority=LIVE):
    record = PersistedAccountingRebaseRecord(
        rebase_id, observed_at, equity, record_authority,
        current.account_scope, "runtime-1", tuple(PeriodCode),
        (current.daily_state.period_id, current.weekly_state.period_id,
         current.monthly_state.period_id),
        (period_for(observed_at, PeriodType.DAILY).period_key,
         period_for(observed_at, PeriodType.WEEKLY).period_key,
         period_for(observed_at, PeriodType.MONTHLY).period_key),
        (D("0"), D("0"), D("0")),
        AccountingRebaseReason.HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE,
        AccountingContinuityStatus.UNAVAILABLE_REBASED,
        AccountingRebaseAuthorizationState.EXPLICITLY_AUTHORIZED,
        AccountingRebaseAuditMarker.DURABLE_CHECKPOINT_REQUIRED,
    )
    next_state = replace(
        current,
        daily_state=_rebased_period(PeriodCode.DAILY, PeriodType.DAILY,
                                    observed_at, equity),
        weekly_state=_rebased_period(PeriodCode.WEEKLY, PeriodType.WEEKLY,
                                     observed_at, equity),
        monthly_state=_rebased_period(PeriodCode.MONTHLY, PeriodType.MONTHLY,
                                      observed_at, equity),
        drawdown_state=PersistedDrawdownState(
            equity, equity, D("0"), D("0"), observed_at
        ),
        last_decision=_decision(observed_at),
        captured_at=observed_at,
        accounting_rebases=current.accounting_rebases + (record,),
        accounting_authority_source=next_authority,
    )
    return next_state, record


def _restricted_store(current):
    startup = LossLimitRuntimeStartupDecision(
        RuntimeDecisionStatus.RESTRICTED, RuntimeLifecycle.RESTRICTED,
        current, StateSource.PERSISTED_STATE, True, False, False, False,
        GovernanceProjection.BLOCK_EXECUTION, (), (), "restricted",
    )
    store = LossLimitRuntimeStateStore()
    result = store.initialize(startup, current.captured_at)
    assert result.status is StoreResultStatus.SUCCEEDED, result
    return store


def _rebase_update(next_state, rebase_id, triggers=(SaveTrigger.ACCOUNTING_REBASE,)):
    return LossLimitRuntimeUpdate(
        next_state, GovernanceProjection.CONTINUE,
        LossLimitRecoveryRequirement(False, (), False, False, False, "none"),
        triggers, 1, 2, OBSERVED, "EXPLICIT_ACCOUNTING_REBASE", rebase_id,
    )


def _stale_failure_app(lifecycle):
    app, _ = application(lifecycle)
    app.state.money_management_runtime_hook = SimpleNamespace(
        hook=SimpleNamespace(
            last_dispatch_status=LossRuntimeDispatchStatus.FAILED,
            last_dispatch_safe_reasons=("lifecycle update failed",),
        )
    )
    return app


class StoppedTelemetryTests(unittest.TestCase):
    def test_1_stopped_reports_current_reason_not_stale_failure(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.STOPPED)
        app = _stale_failure_app(lifecycle)
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        projection = result.public_snapshot.projection
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
        )
        self.assertEqual(projection.entry_permission, LossEntryPermission.UNKNOWN)
        self.assertFalse(projection.new_entry_allowed)
        self.assertIn("lifecycle not running", result.safe_reasons)
        self.assertNotIn("lifecycle update failed", result.safe_reasons)
        self.assertEqual(lifecycle.snapshot_calls, 0)

    def test_2_recovery_required_is_fail_closed(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.RECOVERY_REQUIRED)
        app = _stale_failure_app(lifecycle)
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        projection = result.public_snapshot.projection
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
        )
        self.assertEqual(
            projection.entry_permission, LossEntryPermission.RECOVERY_REQUIRED
        )
        self.assertTrue(projection.recovery_required)
        self.assertFalse(projection.new_entry_allowed)
        self.assertNotIn("lifecycle update failed", result.safe_reasons)
        self.assertEqual(lifecycle.snapshot_calls, 0)

    def test_3_running_genuine_hook_failure_remains_visible(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.RUNNING)
        app = _stale_failure_app(lifecycle)
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        projection = result.public_snapshot.projection
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
        )
        self.assertEqual(projection.entry_permission, LossEntryPermission.UNKNOWN)
        self.assertFalse(projection.new_entry_allowed)
        self.assertIn("lifecycle update failed", result.safe_reasons)

    def test_4_running_healthy_hook_keeps_normal_behaviour(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.RUNNING)
        app, _ = application(lifecycle)
        app.state.money_management_runtime_hook = SimpleNamespace(
            hook=SimpleNamespace(
                last_dispatch_status=LossRuntimeDispatchStatus.APPLIED,
                last_dispatch_safe_reasons=(),
            )
        )
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        projection = result.public_snapshot.projection
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.PROJECTED
        )
        self.assertEqual(projection.entry_permission, LossEntryPermission.ALLOW)
        self.assertTrue(projection.new_entry_allowed)

    def test_5_unknown_lifecycle_is_fail_closed(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.STARTING)
        app = _stale_failure_app(lifecycle)
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        projection = result.public_snapshot.projection
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
        )
        self.assertEqual(projection.entry_permission, LossEntryPermission.UNKNOWN)
        self.assertFalse(projection.new_entry_allowed)
        self.assertIn("lifecycle not running", result.safe_reasons)


class CanonicalAuthorityRebaseTests(unittest.TestCase):
    def test_6_validated_authority_rebase_passes(self):
        current = _locked_paper_state()
        next_state, record = _rebase_artifacts(current, OBSERVED, D("7.91836966"))
        store = _restricted_store(current)
        result = store.apply_update(_rebase_update(next_state, record.rebase_id))
        self.assertEqual(result.status, StoreResultStatus.SUCCEEDED)
        self.assertIs(result.snapshot.lifecycle, RuntimeLifecycle.READY)
        self.assertIs(
            result.snapshot.state.accounting_authority_source, LIVE
        )
        self.assertEqual(
            result.snapshot.state.drawdown_state.drawdown_amount, D("0")
        )

    def test_7_state_shape_only_relaxation_is_rejected(self):
        current = _locked_paper_state()
        next_state, _ = _rebase_artifacts(current, OBSERVED, D("7.91836966"))
        store = _restricted_store(current)
        before = store.get_snapshot().snapshot
        result = store.apply_update(
            _rebase_update(
                next_state, None, (SaveTrigger.STATE_TRANSITION,)
            )
        )
        self.assertEqual(result.status, StoreResultStatus.FAILED)
        self.assertEqual(
            result.failure.code,
            StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,
        )
        self.assertEqual(store.get_snapshot().snapshot.to_dict(), before.to_dict())

    def test_8_forged_rebase_id_is_rejected(self):
        current = _locked_paper_state()
        next_state, _ = _rebase_artifacts(
            current, OBSERVED, D("7.91836966"), rebase_id="real-rebase"
        )
        store = _restricted_store(current)
        before = store.get_snapshot().snapshot
        result = store.apply_update(
            _rebase_update(next_state, "forged-rebase")
        )
        self.assertEqual(result.status, StoreResultStatus.FAILED)
        self.assertEqual(
            result.failure.code,
            StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,
        )
        self.assertEqual(store.get_snapshot().snapshot.to_dict(), before.to_dict())

    def test_9_paper_live_accounting_isolation(self):
        current = _locked_paper_state()
        next_state, record = _rebase_artifacts(
            current, OBSERVED, D("7.91836966"),
            record_authority=PAPER, next_authority=LIVE,
        )
        store = _restricted_store(current)
        result = store.apply_update(_rebase_update(next_state, record.rebase_id))
        self.assertEqual(result.status, StoreResultStatus.FAILED)
        self.assertEqual(
            result.failure.code,
            StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,
        )
        self.assertIs(
            store.get_snapshot().snapshot.state.accounting_authority_source,
            PAPER,
        )
        self.assertIs(
            store.get_snapshot().snapshot.state.risk_state, RiskState.LOCKED
        )

    def test_10_no_execution_authority_semantics_changed(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.STOPPED)
        app = _stale_failure_app(lifecycle)
        execution_state = {"allowed": True}
        app.state.execution = execution_state
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        self.assertEqual(execution_state, {"allowed": True})
        self.assertFalse(result.public_snapshot.projection.new_entry_allowed)
        self.assertEqual(
            result.public_snapshot.projection.entry_permission,
            LossEntryPermission.UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main()
