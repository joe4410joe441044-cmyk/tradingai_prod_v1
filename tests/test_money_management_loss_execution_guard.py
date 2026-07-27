import threading
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.money_management.enums import RiskState
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LifecycleOperationStatus,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementApplicationRegistration,
    MoneyManagementSafeApplicationStatus,
)
from backend.money_management.loss_execution_guard import (
    LossExecutionEntryGuardDispatcher,
    LossGovernanceProjectionReader,
    dispatch_money_management_execution_entry_guard,
)
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionGuardReason,
    LossExecutionGuardRequest,
    LossExecutionOperation,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceBoundaryReason,
    LossGovernanceProjection,
    LossGovernancePublicSnapshot,
)
from backend.money_management.loss_reason_models import BlockReason, DiagnosticReason
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
)


NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


class TrapLifecycle:
    def get_status(self):
        raise AssertionError("runtime status must not be read")

    def get_snapshot(self):
        raise AssertionError("runtime snapshot must not be read")


def projection(permission=LossEntryPermission.ALLOW):
    if permission is LossEntryPermission.ALLOW:
        return LossGovernanceProjection(
            permission,
            True,
            None,
            RiskState.NORMAL,
            GovernanceProjection.CONTINUE,
            False,
            (),
            NOW,
        )
    if permission is LossEntryPermission.BLOCK:
        return LossGovernanceProjection(
            permission,
            False,
            BlockReason.DAILY_LOSS_BLOCK,
            RiskState.LOCKED,
            GovernanceProjection.BLOCK_EXECUTION,
            False,
            (),
            NOW,
        )
    if permission is LossEntryPermission.RECOVERY_REQUIRED:
        return LossGovernanceProjection(
            permission,
            False,
            LossGovernanceBoundaryReason.RECOVERY_REQUIRED,
            None,
            GovernanceProjection.RECOVERY_REQUIRED,
            True,
            (DiagnosticReason.METRIC_UNAVAILABLE,),
            NOW,
        )
    return LossGovernanceProjection(
        permission,
        False,
        LossGovernanceBoundaryReason.UNKNOWN_STATE,
        None,
        None,
        False,
        (DiagnosticReason.METRIC_UNAVAILABLE,),
        NOW,
    )


def public_snapshot(permission=LossEntryPermission.ALLOW, revision=2, sequence=3):
    value = projection(permission)
    return LossGovernancePublicSnapshot(
        value, revision, sequence, value.generated_at
    )


def registration(
    lifecycle_state=ApplicationLifecycleState.RUNNING,
    revision=2,
    sequence=3,
):
    safe = MoneyManagementSafeApplicationStatus(
        True,
        CompositionReadinessStatus.READY,
        lifecycle_state,
        lifecycle_state is ApplicationLifecycleState.RUNNING,
        "READY",
        False,
        lifecycle_state is ApplicationLifecycleState.RECOVERY_REQUIRED,
        False,
        revision,
        sequence,
        None,
    )
    return MoneyManagementApplicationRegistration(
        CompositionReadinessStatus.READY,
        TrapLifecycle(),
        LifecycleOperationStatus.SUCCEEDED,
        None,
        safe,
    )


def application(
    permission=LossEntryPermission.ALLOW,
    lifecycle_state=ApplicationLifecycleState.RUNNING,
    include_registration=True,
    include_projection=True,
):
    state = SimpleNamespace()
    if include_registration:
        state.money_management = registration(lifecycle_state)
    if include_projection:
        state.money_management_governance_projection = public_snapshot(permission)
    state.governance = {"enabled": True}
    state.execution = {"enabled": True}
    state.bot_manager = {"state": "RUNNING"}
    return SimpleNamespace(state=state)


def request(
    operation=LossExecutionOperation.NEW_BUY,
    expected_revision=None,
    expected_sequence=None,
    at=NOW + timedelta(seconds=1),
):
    return LossExecutionGuardRequest(
        operation,
        at,
        expected_revision,
        expected_sequence,
    )


class CountingReader(LossGovernanceProjectionReader):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def read(self, app):
        self.calls += 1
        return super().read(app)


class ExecutionEntryGuardTests(unittest.TestCase):
    def test_allow_new_buy_and_sell(self):
        dispatcher = LossExecutionEntryGuardDispatcher()
        app = application()
        for operation in (
            LossExecutionOperation.NEW_BUY,
            LossExecutionOperation.NEW_SELL,
        ):
            with self.subTest(operation=operation):
                result = dispatcher.dispatch(app, request(operation))
                self.assertTrue(result.allowed)
                self.assertEqual(
                    result.decision, LossExecutionEntryDecision.ALLOW
                )
                self.assertEqual(
                    result.reason, LossExecutionGuardReason.ENTRY_ALLOWED.value
                )
                self.assertEqual((result.revision, result.sequence), (2, 3))

    def test_block_recovery_and_unknown_projection(self):
        expected = (
            (
                LossEntryPermission.BLOCK,
                LossExecutionEntryDecision.BLOCK,
                BlockReason.DAILY_LOSS_BLOCK.value,
            ),
            (
                LossEntryPermission.RECOVERY_REQUIRED,
                LossExecutionEntryDecision.RECOVERY_REQUIRED,
                LossGovernanceBoundaryReason.RECOVERY_REQUIRED.value,
            ),
            (
                LossEntryPermission.UNKNOWN,
                LossExecutionEntryDecision.UNKNOWN,
                LossGovernanceBoundaryReason.UNKNOWN_STATE.value,
            ),
        )
        for permission, decision, reason in expected:
            with self.subTest(permission=permission):
                result = LossExecutionEntryGuardDispatcher().dispatch(
                    application(permission), request()
                )
                self.assertFalse(result.allowed)
                self.assertEqual(result.decision, decision)
                self.assertEqual(result.reason, reason)

    def test_non_entry_operations_always_pass_without_projection_read(self):
        reader = CountingReader()
        dispatcher = LossExecutionEntryGuardDispatcher(reader)
        app = application(
            include_registration=False,
            include_projection=False,
        )
        operations = (
            LossExecutionOperation.POSITION_CLOSE,
            LossExecutionOperation.REDUCE_ONLY,
            LossExecutionOperation.PARTIAL_CLOSE,
            LossExecutionOperation.FLATTEN,
            LossExecutionOperation.EMERGENCY_FLATTEN,
            LossExecutionOperation.CANCEL,
        )
        for operation in operations:
            with self.subTest(operation=operation):
                result = dispatcher.dispatch(app, request(operation))
                self.assertTrue(result.allowed)
                self.assertEqual(
                    result.reason,
                    LossExecutionGuardReason.OPERATION_NOT_GUARDED.value,
                )
                self.assertIsNone(result.revision)
                self.assertIsNone(result.sequence)
        self.assertEqual(reader.calls, 0)

    def test_invalid_dispatcher_still_never_blocks_non_entry_operation(self):
        result = dispatch_money_management_execution_entry_guard(
            application(
                include_registration=False,
                include_projection=False,
            ),
            object(),
            request(LossExecutionOperation.EMERGENCY_FLATTEN),
        )
        self.assertTrue(result.allowed)

    def test_projection_and_registration_missing_fail_closed(self):
        missing_projection = LossExecutionEntryGuardDispatcher().dispatch(
            application(include_projection=False),
            request(),
        )
        missing_registration = LossExecutionEntryGuardDispatcher().dispatch(
            application(include_registration=False),
            request(),
        )
        self.assertFalse(missing_projection.allowed)
        self.assertEqual(
            missing_projection.reason,
            LossExecutionGuardReason.PROJECTION_MISSING.value,
        )
        self.assertFalse(missing_registration.allowed)
        self.assertEqual(
            missing_registration.reason,
            LossExecutionGuardReason.REGISTRATION_UNAVAILABLE.value,
        )

    def test_stopped_lifecycle_fails_closed_without_runtime_access(self):
        result = LossExecutionEntryGuardDispatcher().dispatch(
            application(lifecycle_state=ApplicationLifecycleState.STOPPED),
            request(),
        )
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reason,
            LossExecutionGuardReason.LIFECYCLE_NOT_RUNNING.value,
        )

    def test_revision_or_sequence_mismatch_fails_closed(self):
        dispatcher = LossExecutionEntryGuardDispatcher()
        for revision, sequence in ((1, 3), (2, 4)):
            with self.subTest(revision=revision, sequence=sequence):
                result = dispatcher.dispatch(
                    application(),
                    request(
                        expected_revision=revision,
                        expected_sequence=sequence,
                    ),
                )
                self.assertFalse(result.allowed)
                self.assertEqual(
                    result.reason,
                    LossExecutionGuardReason.PROJECTION_REVISION_MISMATCH.value,
                )

    def test_projection_older_than_registration_fails_closed(self):
        app = application()
        app.state.money_management = registration(revision=4, sequence=5)
        result = LossExecutionEntryGuardDispatcher().dispatch(app, request())
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reason,
            LossExecutionGuardReason.PROJECTION_INVALID.value,
        )

    def test_future_projection_timestamp_fails_closed(self):
        app = application()
        result = LossExecutionEntryGuardDispatcher().dispatch(
            app,
            request(at=NOW - timedelta(seconds=1)),
        )
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reason,
            LossExecutionGuardReason.PROJECTION_TIMESTAMP_INVALID.value,
        )

    def test_duplicate_read_is_deterministic_and_has_no_mutation(self):
        app = application()
        before_registration = app.state.money_management
        before_projection = app.state.money_management_governance_projection
        before_governance = dict(app.state.governance)
        before_execution = dict(app.state.execution)
        before_bot = dict(app.state.bot_manager)
        dispatcher = LossExecutionEntryGuardDispatcher()
        first = dispatcher.dispatch(app, request())
        second = dispatcher.dispatch(app, request())
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertIs(app.state.money_management, before_registration)
        self.assertIs(
            app.state.money_management_governance_projection,
            before_projection,
        )
        self.assertEqual(app.state.governance, before_governance)
        self.assertEqual(app.state.execution, before_execution)
        self.assertEqual(app.state.bot_manager, before_bot)

    def test_concurrent_reads_are_deterministic(self):
        app = application()
        dispatcher = LossExecutionEntryGuardDispatcher()
        results = []

        def run():
            results.append(dispatcher.dispatch(app, request()).to_dict())

        threads = [threading.Thread(target=run) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 12)
        self.assertTrue(all(item == results[0] for item in results))

    def test_result_is_immutable_and_safe(self):
        result = LossExecutionEntryGuardDispatcher().dispatch(
            application(), request()
        )
        with self.assertRaises(FrozenInstanceError):
            result.allowed = False
        payload = result.to_dict()
        self.assertEqual(
            set(payload),
            {
                "operation",
                "decision",
                "allowed",
                "reason",
                "generatedAt",
                "revision",
                "sequence",
            },
        )
        text = repr(payload).lower()
        for forbidden in (
            "botmanager",
            "runtime_snapshot",
            "fingerprint",
            "exception",
            "secret",
            "persistence",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
