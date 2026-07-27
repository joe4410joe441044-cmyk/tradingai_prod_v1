import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from backend.money_management.enums import RiskState
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LifecycleOperationStatus,
    LossLimitApplicationStatus,
    LossLimitLifecycleOperationResult,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementApplicationRegistration,
    MoneyManagementSafeApplicationStatus,
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
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
)
from backend.money_management.loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
)
from backend.money_management.loss_runtime_event_models import LossRuntimeEventType
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    RuntimeLifecycle,
    StateSource,
)
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetrics,
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_metrics_source import (
    LossRuntimeMetricsSource,
)
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
    dispatch_money_management_runtime_update,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType


D = Decimal
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def initial_state(at=NOW):
    def period(code, typ):
        value = period_for(at, typ)
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
            at,
        )

    decision = LossReasonContract(
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
    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION,
        "primary",
        "USDT",
        period(PeriodCode.DAILY, PeriodType.DAILY),
        period(PeriodCode.WEEKLY, PeriodType.WEEKLY),
        period(PeriodCode.MONTHLY, PeriodType.MONTHLY),
        PersistedDrawdownState(D("1000"), D("1000"), D("0"), D("0"), at),
        PersistedCashFlowState(False, (), D("0")),
        decision,
        at,
    )


def runtime_snapshot(at=NOW):
    return LossLimitRuntimeSnapshot(
        RuntimeLifecycle.READY,
        initial_state(at),
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


def metrics(revision="8", at=NOW + timedelta(seconds=1), **overrides):
    values = {
        "captured_at": at,
        "source_revision": revision,
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


class Source(LossRuntimeMetricsSource):
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def read_metrics(self, request):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        if isinstance(value, LossRuntimeMetricsReadResult):
            return value
        return LossRuntimeMetricsReadResult(
            LossRuntimeMetricsReadStatus.AVAILABLE, value, ()
        )


class Lifecycle:
    def __init__(
        self,
        state=ApplicationLifecycleState.RUNNING,
        operation_status=LifecycleOperationStatus.SUCCEEDED,
        stop_on_second_status=False,
    ):
        self.state = state
        self.operation_status = operation_status
        self.snapshot = runtime_snapshot()
        self.apply_calls = 0
        self.status_calls = 0
        self.stop_on_second_status = stop_on_second_status

    def get_status(self):
        self.status_calls += 1
        if self.stop_on_second_status and self.status_calls >= 2:
            self.state = ApplicationLifecycleState.STOPPING
        return LossLimitApplicationStatus(
            self.state,
            CompositionReadinessStatus.READY,
            self.state is ApplicationLifecycleState.RUNNING,
            self.snapshot.lifecycle,
            False,
            self.state is ApplicationLifecycleState.RECOVERY_REQUIRED,
            False,
            self.snapshot.revision,
            self.snapshot.sequence,
            None,
            None,
        )

    def get_snapshot(self):
        return self.snapshot

    def apply_update(self, request):
        self.apply_calls += 1
        if self.operation_status in (
            LifecycleOperationStatus.SUCCEEDED,
            LifecycleOperationStatus.PARTIAL,
        ):
            self.snapshot = LossLimitRuntimeSnapshot(
                RuntimeLifecycle.READY,
                request.next_state,
                StateSource.CURRENT_RUNTIME_STATE,
                request.governance_projection,
                request.recovery_requirement,
                request.save_triggers,
                self.snapshot.revision + 1,
                request.event_sequence,
                self.snapshot.initialized_at,
                request.occurred_at,
                request.transition_reason,
            )
        return LossLimitLifecycleOperationResult(
            self.operation_status,
            self.state,
            None,
            None
            if self.operation_status
            not in (
                LifecycleOperationStatus.FAILED,
                LifecycleOperationStatus.REJECTED,
            )
            else __import__(
                "backend.money_management.loss_application_models",
                fromlist=["LossLimitApplicationFailure"],
            ).LossLimitApplicationFailure(
                __import__(
                    "backend.money_management.loss_application_models",
                    fromlist=["ApplicationFailureCode"],
                ).ApplicationFailureCode.LOSS_APPLICATION_OPERATION_FAILED,
                "safe failure",
            ),
        )


def app_with(lifecycle=None, composition=CompositionReadinessStatus.READY):
    lifecycle = lifecycle or Lifecycle()
    enabled = composition is not CompositionReadinessStatus.DISABLED
    safe = MoneyManagementSafeApplicationStatus(
        enabled,
        composition,
        lifecycle.state if enabled else None,
        enabled and lifecycle.state is ApplicationLifecycleState.RUNNING,
        "READY" if enabled else None,
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
    return SimpleNamespace(state=SimpleNamespace(money_management=registration))


def request():
    return LossRuntimeMetricsReadRequest(
        "bot-manager", NOW + timedelta(seconds=2), timedelta(minutes=1)
    )


class DispatcherTests(unittest.TestCase):
    def test_disabled_is_noop_before_metrics_read(self):
        source = Source([metrics()])
        lifecycle = Lifecycle()
        app = app_with(lifecycle, CompositionReadinessStatus.DISABLED)
        result = LossRuntimeUpdateDispatcher(source).dispatch(
            app, request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        self.assertEqual(result.status, LossRuntimeDispatchStatus.DISABLED)
        self.assertEqual(source.calls, 0)
        self.assertEqual(lifecycle.apply_calls, 0)

    def test_missing_registration_and_not_running_fail_closed(self):
        source = Source([metrics()])
        missing = SimpleNamespace(state=SimpleNamespace())
        stopped_lifecycle = Lifecycle(ApplicationLifecycleState.STOPPED)
        stopped = app_with(stopped_lifecycle)
        result_missing = LossRuntimeUpdateDispatcher(source).dispatch(
            missing, request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        result_stopped = LossRuntimeUpdateDispatcher(source).dispatch(
            stopped, request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        self.assertEqual(
            result_missing.status, LossRuntimeDispatchStatus.UNAVAILABLE
        )
        self.assertEqual(result_stopped.status, LossRuntimeDispatchStatus.REJECTED)
        self.assertFalse(result_stopped.new_entry_allowed)
        self.assertEqual(source.calls, 0)

    def test_normal_dispatch_calls_each_stage_once(self):
        source = Source([metrics()])
        lifecycle = Lifecycle()
        dispatcher = LossRuntimeUpdateDispatcher(source)
        result = dispatch_money_management_runtime_update(
            app_with(lifecycle),
            dispatcher,
            request(),
            LossRuntimeEventType.EQUITY_UPDATE,
        )
        self.assertEqual(result.status, LossRuntimeDispatchStatus.APPLIED)
        self.assertEqual(source.calls, 1)
        self.assertEqual(lifecycle.apply_calls, 1)
        self.assertEqual(result.runtime_sequence, 2)

    def test_duplicate_and_conflict_do_not_reapply(self):
        first = metrics()
        source = Source(
            [
                first,
                first,
                metrics(
                    at=NOW + timedelta(seconds=2),
                    equity=D("999"),
                    balance=D("999"),
                    peak_equity=D("1000"),
                    drawdown=D("0.1"),
                ),
            ]
        )
        lifecycle = Lifecycle()
        dispatcher = LossRuntimeUpdateDispatcher(source)
        app = app_with(lifecycle)
        applied = dispatcher.dispatch(app, request(), LossRuntimeEventType.EQUITY_UPDATE)
        duplicate = dispatcher.dispatch(
            app, request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        conflict = dispatcher.dispatch(
            app, request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        self.assertEqual(applied.status, LossRuntimeDispatchStatus.APPLIED)
        self.assertEqual(duplicate.status, LossRuntimeDispatchStatus.IDEMPOTENT)
        self.assertEqual(conflict.status, LossRuntimeDispatchStatus.CONFLICT)
        self.assertEqual(lifecycle.apply_calls, 1)

    def test_partial_stale_and_source_exception_never_update(self):
        partial_metrics = metrics(data_quality=LossRuntimeDataQuality.PARTIAL)
        cases = (
            LossRuntimeMetricsReadResult(
                LossRuntimeMetricsReadStatus.PARTIAL,
                partial_metrics,
                ("missing",),
            ),
            LossRuntimeMetricsReadResult(
                LossRuntimeMetricsReadStatus.STALE,
                metrics(data_quality=LossRuntimeDataQuality.STALE),
                ("stale",),
            ),
            RuntimeError("secret"),
        )
        expected = (
            LossRuntimeDispatchStatus.UNAVAILABLE,
            LossRuntimeDispatchStatus.STALE,
            LossRuntimeDispatchStatus.FAILED,
        )
        for value, target in zip(cases, expected):
            with self.subTest(target=target):
                lifecycle = Lifecycle()
                result = LossRuntimeUpdateDispatcher(Source([value])).dispatch(
                    app_with(lifecycle),
                    request(),
                    LossRuntimeEventType.EQUITY_UPDATE,
                )
                self.assertEqual(result.status, target)
                self.assertEqual(lifecycle.apply_calls, 0)

    def test_evaluation_exception_and_lifecycle_failure_are_safe(self):
        def explode(_):
            raise RuntimeError("secret")

        lifecycle = Lifecycle()
        failed_evaluation = LossRuntimeUpdateDispatcher(
            Source([metrics()]),
            LossRuntimeEvaluationBridge(domain_evaluator=explode),
        ).dispatch(
            app_with(lifecycle), request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        failed_lifecycle = Lifecycle(
            operation_status=LifecycleOperationStatus.FAILED
        )
        failed_update = LossRuntimeUpdateDispatcher(Source([metrics()])).dispatch(
            app_with(failed_lifecycle),
            request(),
            LossRuntimeEventType.EQUITY_UPDATE,
        )
        self.assertEqual(
            failed_evaluation.status, LossRuntimeDispatchStatus.FAILED
        )
        self.assertEqual(lifecycle.apply_calls, 0)
        self.assertEqual(failed_update.status, LossRuntimeDispatchStatus.FAILED)
        self.assertFalse(failed_update.new_entry_allowed)

    def test_lifecycle_partial_is_applied_with_durability_pending(self):
        lifecycle = Lifecycle(operation_status=LifecycleOperationStatus.PARTIAL)
        result = LossRuntimeUpdateDispatcher(Source([metrics()])).dispatch(
            app_with(lifecycle), request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        self.assertEqual(result.status, LossRuntimeDispatchStatus.APPLIED)
        self.assertTrue(result.durability_pending)

    def test_shutdown_race_rechecks_lifecycle_before_apply(self):
        lifecycle = Lifecycle(stop_on_second_status=True)
        result = LossRuntimeUpdateDispatcher(Source([metrics()])).dispatch(
            app_with(lifecycle), request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        self.assertEqual(result.status, LossRuntimeDispatchStatus.REJECTED)
        self.assertEqual(lifecycle.apply_calls, 0)

    def test_concurrent_dispatch_is_serial_and_sequences_are_unique(self):
        source = Source(
            [
                metrics("8", NOW + timedelta(seconds=1)),
                metrics("9", NOW + timedelta(seconds=2)),
            ]
        )
        lifecycle = Lifecycle()
        dispatcher = LossRuntimeUpdateDispatcher(source)
        app = app_with(lifecycle)
        results = []

        def run():
            results.append(
                dispatcher.dispatch(
                    app, request(), LossRuntimeEventType.EQUITY_UPDATE
                )
            )

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(
            [item.status for item in results].count(
                LossRuntimeDispatchStatus.APPLIED
            ),
            2,
        )
        self.assertEqual(lifecycle.apply_calls, 2)
        self.assertEqual(lifecycle.snapshot.sequence, 3)

    def test_multiple_application_dispatchers_are_isolated(self):
        lifecycle_a, lifecycle_b = Lifecycle(), Lifecycle()
        dispatcher_a = LossRuntimeUpdateDispatcher(Source([metrics()]))
        dispatcher_b = LossRuntimeUpdateDispatcher(Source([metrics()]))
        result_a = dispatcher_a.dispatch(
            app_with(lifecycle_a), request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        result_b = dispatcher_b.dispatch(
            app_with(lifecycle_b), request(), LossRuntimeEventType.EQUITY_UPDATE
        )
        self.assertEqual(result_a.status, LossRuntimeDispatchStatus.APPLIED)
        self.assertEqual(result_b.status, LossRuntimeDispatchStatus.APPLIED)
        self.assertEqual(lifecycle_a.snapshot.sequence, 2)
        self.assertEqual(lifecycle_b.snapshot.sequence, 2)


if __name__ == "__main__":
    unittest.main()
