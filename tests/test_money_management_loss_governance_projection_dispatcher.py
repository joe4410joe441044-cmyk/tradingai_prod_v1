import threading
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from backend.money_management.enums import RiskState
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LifecycleOperationStatus,
    LossLimitApplicationStatus,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementApplicationRegistration,
    MoneyManagementSafeApplicationStatus,
)
from backend.money_management.loss_governance_projection_dispatcher import (
    LossGovernanceProjectionDispatcher,
    dispatch_money_management_governance_projection,
    get_money_management_governance_projection,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceBoundaryReason,
    LossGovernanceProjectionDispatchStatus,
)
from backend.money_management.loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION,
    PeriodCode,
    PersistedCashFlowState,
    PersistedDrawdownState,
    PersistedLossPeriodState,
    PersistedLossState,
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
    RecoveryReason,
    RuntimeLifecycle,
    StateSource,
)
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType


D = Decimal
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def reason(
    state=RiskState.NORMAL,
    action=RecommendedAction.CONTINUE,
    primary=ReasonCode.NONE,
    blocks=(),
    fail_closed=False,
):
    return LossReasonContract(
        "money-management-loss-reason/v1",
        NOW,
        state,
        action,
        primary,
        (),
        (),
        tuple(blocks),
        (),
        (),
        (),
        fail_closed,
    )


def loss_state(last_reason=None):
    def period(code, typ):
        value = period_for(NOW, typ)
        return PersistedLossPeriodState(
            code,
            value.period_key,
            value.start_at,
            value.end_at,
            D("1000"),
            D("0"),
            D("0"),
            D("0"),
            D("0"),
            NOW,
        )

    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION,
        "primary",
        "USDT",
        period(PeriodCode.DAILY, PeriodType.DAILY),
        period(PeriodCode.WEEKLY, PeriodType.WEEKLY),
        period(PeriodCode.MONTHLY, PeriodType.MONTHLY),
        PersistedDrawdownState(D("1000"), D("1000"), D("0"), D("0"), NOW),
        PersistedCashFlowState(False, (), D("0")),
        last_reason or reason(),
        NOW,
    )


def runtime_snapshot(
    projection=GovernanceProjection.CONTINUE,
    recovery=False,
    last_reason=None,
    revision=2,
    sequence=3,
):
    return LossLimitRuntimeSnapshot(
        RuntimeLifecycle.RECOVERY_REQUIRED
        if recovery
        else RuntimeLifecycle.RESTRICTED
        if projection
        in (
            GovernanceProjection.HOLD_NEW_ENTRIES,
            GovernanceProjection.BLOCK_EXECUTION,
        )
        else RuntimeLifecycle.READY,
        loss_state(last_reason),
        StateSource.CURRENT_RUNTIME_STATE,
        projection,
        LossLimitRecoveryRequirement(
            recovery,
            ()
            if not recovery
            else (RecoveryReason.STATE_UNAVAILABLE,),
            False,
            False,
            recovery,
            "recovery required" if recovery else "none",
        ),
        (),
        revision,
        sequence,
        NOW,
        NOW,
        "runtime",
    )


class Lifecycle:
    def __init__(
        self,
        application_state=ApplicationLifecycleState.RUNNING,
        snapshot=None,
    ):
        self.application_state = application_state
        self.snapshot = snapshot or runtime_snapshot()
        self.status_calls = 0
        self.snapshot_calls = 0

    def get_status(self):
        self.status_calls += 1
        return LossLimitApplicationStatus(
            self.application_state,
            CompositionReadinessStatus.READY,
            self.application_state is ApplicationLifecycleState.RUNNING,
            self.snapshot.lifecycle,
            False,
            self.application_state
            is ApplicationLifecycleState.RECOVERY_REQUIRED,
            False,
            self.snapshot.revision,
            self.snapshot.sequence,
            None,
            None,
        )

    def get_snapshot(self):
        self.snapshot_calls += 1
        return self.snapshot


def application(lifecycle=None, composition=CompositionReadinessStatus.READY):
    lifecycle = lifecycle or Lifecycle()
    enabled = composition is not CompositionReadinessStatus.DISABLED
    safe = MoneyManagementSafeApplicationStatus(
        enabled,
        composition,
        lifecycle.application_state if enabled else None,
        enabled
        and lifecycle.application_state is ApplicationLifecycleState.RUNNING,
        lifecycle.snapshot.lifecycle.value if enabled else None,
        False,
        composition is CompositionReadinessStatus.RECOVERY_REQUIRED,
        False,
        lifecycle.snapshot.revision if enabled else None,
        lifecycle.snapshot.sequence if enabled else None,
        None,
    )
    registration = MoneyManagementApplicationRegistration(
        composition,
        lifecycle if enabled else None,
        LifecycleOperationStatus.SUCCEEDED if enabled else None,
        None,
        safe,
    )
    return (
        SimpleNamespace(
            state=SimpleNamespace(money_management=registration),
        ),
        registration,
    )


class GovernanceProjectionDispatcherTests(unittest.TestCase):
    def test_normal_projection_is_published_without_replacing_registration(self):
        app, registration = application()
        governance_state = {"enabled": True}
        execution_state = {"allowed": True}
        app.state.governance = governance_state
        app.state.execution = execution_state
        dispatcher = LossGovernanceProjectionDispatcher(timestamp_source=lambda: NOW)
        result = dispatch_money_management_governance_projection(app, dispatcher)
        public = get_money_management_governance_projection(app)
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.PROJECTED
        )
        self.assertIs(public, result.public_snapshot)
        self.assertEqual(
            public.projection.entry_permission, LossEntryPermission.ALLOW
        )
        self.assertEqual(public.revision, 2)
        self.assertEqual(public.sequence, 3)
        self.assertIs(app.state.money_management, registration)
        self.assertEqual(governance_state, {"enabled": True})
        self.assertEqual(execution_state, {"allowed": True})

    def test_block_projection_reuses_reason(self):
        locked = reason(
            RiskState.LOCKED,
            RecommendedAction.BLOCK_EXECUTION,
            ReasonCode.DAILY_LOSS_BLOCK,
            (BlockReason.DAILY_LOSS_BLOCK,),
        )
        app, _ = application(
            Lifecycle(
                snapshot=runtime_snapshot(
                    GovernanceProjection.BLOCK_EXECUTION,
                    last_reason=locked,
                )
            )
        )
        result = LossGovernanceProjectionDispatcher().dispatch(app)
        self.assertEqual(
            result.public_snapshot.projection.entry_permission,
            LossEntryPermission.BLOCK,
        )
        self.assertIs(
            result.public_snapshot.projection.block_reason,
            BlockReason.DAILY_LOSS_BLOCK,
        )

    def test_recovery_state_is_projected_without_runtime_snapshot_read(self):
        lifecycle = Lifecycle(ApplicationLifecycleState.RECOVERY_REQUIRED)
        app, _ = application(lifecycle)
        result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app)
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
        )
        self.assertEqual(
            result.public_snapshot.projection.entry_permission,
            LossEntryPermission.RECOVERY_REQUIRED,
        )
        self.assertIs(
            result.public_snapshot.projection.block_reason,
            LossGovernanceBoundaryReason.RECOVERY_REQUIRED,
        )
        self.assertEqual(lifecycle.snapshot_calls, 0)

    def test_missing_registration_and_stopped_lifecycle_are_unknown(self):
        missing = SimpleNamespace(state=SimpleNamespace())
        missing_result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(missing)
        stopped_lifecycle = Lifecycle(ApplicationLifecycleState.STOPPED)
        stopped, _ = application(stopped_lifecycle)
        stopped_result = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(stopped)
        for result in (missing_result, stopped_result):
            projection = result.public_snapshot.projection
            self.assertEqual(
                result.status,
                LossGovernanceProjectionDispatchStatus.FAIL_CLOSED,
            )
            self.assertEqual(
                projection.entry_permission, LossEntryPermission.UNKNOWN
            )
            self.assertFalse(projection.new_entry_allowed)
            self.assertIs(
                projection.block_reason,
                LossGovernanceBoundaryReason.UNKNOWN_STATE,
            )
        self.assertEqual(stopped_lifecycle.snapshot_calls, 0)

    def test_builder_failure_is_sanitized_and_fail_closed(self):
        def explode(_):
            raise RuntimeError("secret /private/path")

        app, _ = application()
        result = LossGovernanceProjectionDispatcher(
            projection_builder=explode,
            timestamp_source=lambda: NOW,
        ).dispatch(app)
        self.assertEqual(
            result.status, LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
        )
        self.assertFalse(
            result.public_snapshot.projection.new_entry_allowed
        )
        self.assertNotIn("secret", repr(result))
        self.assertNotIn("/private", repr(result))

    def test_duplicate_update_is_idempotent(self):
        app, _ = application()
        dispatcher = LossGovernanceProjectionDispatcher(timestamp_source=lambda: NOW)
        first = dispatcher.dispatch(app)
        original = get_money_management_governance_projection(app)
        second = dispatcher.dispatch(app)
        self.assertEqual(
            first.status, LossGovernanceProjectionDispatchStatus.PROJECTED
        )
        self.assertEqual(
            second.status, LossGovernanceProjectionDispatchStatus.IDEMPOTENT
        )
        self.assertFalse(second.updated)
        self.assertIs(
            get_money_management_governance_projection(app), original
        )

    def test_concurrent_updates_are_serial_and_not_duplicated(self):
        app, _ = application()
        dispatcher = LossGovernanceProjectionDispatcher(timestamp_source=lambda: NOW)
        results = []

        def run():
            results.append(dispatcher.dispatch(app))

        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(
            sum(
                result.status
                is LossGovernanceProjectionDispatchStatus.PROJECTED
                for result in results
            ),
            1,
        )
        self.assertEqual(
            sum(
                result.status
                is LossGovernanceProjectionDispatchStatus.IDEMPOTENT
                for result in results
            ),
            7,
        )

    def test_public_snapshot_contains_no_raw_runtime_or_secret_fields(self):
        app, _ = application()
        payload = LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ).dispatch(app).public_snapshot.to_dict()
        text = repr(payload).lower()
        for forbidden in (
            "botmanager",
            "runtime_snapshot",
            "fingerprint",
            "exception",
            "persistence",
            "secret",
        ):
            self.assertNotIn(forbidden, text)
        self.assertEqual(
            set(payload),
            {"projection", "revision", "sequence", "generatedAt"},
        )


if __name__ == "__main__":
    unittest.main()
