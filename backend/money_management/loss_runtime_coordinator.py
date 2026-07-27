"""MM-4E upper runtime coordinator; child coordinators are injected."""
from threading import RLock

from .loss_runtime_checkpoint_models import (
    CheckpointMode,
    CheckpointStatus,
    LossLimitRuntimeCheckpointRequest,
    LossLimitRuntimeCheckpointResult,
)
from .loss_runtime_checkpoint_policy import (
    build_loss_limit_checkpoint_policy_decision,
)
from .loss_runtime_coordination_models import (
    LossLimitRuntimeCoordinationFailure,
    LossLimitRuntimeCoordinationResult,
    LossLimitRuntimeStopRequest,
    RuntimeCoordinationFailureCode,
    RuntimeCoordinationStatus,
    RuntimeOperationType,
)
from .loss_runtime_integration_models import GovernanceProjection, RuntimeLifecycle
from .loss_runtime_startup_models import (
    LossLimitRuntimeStartupCoordinationResult,
    LossLimitRuntimeStartupRequest,
    StartupCoordinationStatus,
)
from .loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
    LossLimitRuntimeStoreResult,
    LossLimitRuntimeUpdate,
    StoreResultStatus,
)


def _new_entry_allowed(snapshot):
    return (
        snapshot is not None
        and snapshot.lifecycle is RuntimeLifecycle.READY
        and snapshot.governance_projection is GovernanceProjection.CONTINUE
    )


class LossLimitRuntimeCoordinator:
    def __init__(self, startup_coordinator, runtime_store, checkpoint_coordinator):
        if (
            startup_coordinator is None
            or runtime_store is None
            or checkpoint_coordinator is None
        ):
            raise TypeError("all child coordinators are required")
        self._startup = startup_coordinator
        self._store = runtime_store
        self._checkpoint = checkpoint_coordinator
        self._lock = RLock()

    @staticmethod
    def _failed(operation, code, message, snapshot=None, runtime_status=None):
        return LossLimitRuntimeCoordinationResult(
            RuntimeCoordinationStatus.FAILED,
            operation,
            runtime_status,
            None,
            snapshot,
            False,
            False,
            False,
            False,
            False,
            snapshot is not None
            and snapshot.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED,
            _new_entry_allowed(snapshot),
            LossLimitRuntimeCoordinationFailure(code, message),
            snapshot.save_triggers if snapshot is not None else (),
        )

    @staticmethod
    def _without_checkpoint(operation, runtime_status, snapshot, status):
        recovery = snapshot.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED
        return LossLimitRuntimeCoordinationResult(
            status,
            operation,
            runtime_status,
            None,
            snapshot,
            True,
            False,
            False,
            True,
            False,
            recovery,
            _new_entry_allowed(snapshot),
            None,
            snapshot.save_triggers,
        )

    def _with_checkpoint(
        self,
        operation,
        runtime_status,
        snapshot,
        policy,
        requested_at,
        checkpoint_request=None,
    ):
        mode = {
            RuntimeOperationType.STARTUP: CheckpointMode.STARTUP_INITIAL_STATE,
            RuntimeOperationType.UPDATE: CheckpointMode.RUNTIME_TRANSITION,
            RuntimeOperationType.STOP: CheckpointMode.SHUTDOWN,
            RuntimeOperationType.MANUAL_CHECKPOINT: CheckpointMode.MANUAL,
        }[operation]
        request = checkpoint_request or LossLimitRuntimeCheckpointRequest(
            policy.trigger, snapshot.revision, snapshot.sequence, requested_at, mode
        )
        try:
            result = self._checkpoint.checkpoint(request)
        except Exception:
            return LossLimitRuntimeCoordinationResult(
                RuntimeCoordinationStatus.PARTIAL,
                operation,
                runtime_status,
                CheckpointStatus.FAILED,
                snapshot,
                True,
                True,
                True,
                False,
                True,
                snapshot.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED,
                _new_entry_allowed(snapshot),
                LossLimitRuntimeCoordinationFailure(
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_CHECKPOINT_FAILED,
                    "checkpoint failed",
                ),
                snapshot.save_triggers,
            )
        if not isinstance(result, LossLimitRuntimeCheckpointResult):
            return LossLimitRuntimeCoordinationResult(
                RuntimeCoordinationStatus.FAILED,
                operation,
                runtime_status,
                None,
                snapshot,
                True,
                True,
                True,
                False,
                True,
                snapshot.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED,
                _new_entry_allowed(snapshot),
                LossLimitRuntimeCoordinationFailure(
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "checkpoint result invalid",
                ),
                snapshot.save_triggers,
            )
        successful = result.status in (
            CheckpointStatus.SUCCEEDED,
            CheckpointStatus.IDEMPOTENT,
        )
        if successful != result.checkpoint_succeeded:
            return LossLimitRuntimeCoordinationResult(
                RuntimeCoordinationStatus.FAILED,
                operation,
                runtime_status,
                result.status,
                snapshot,
                True,
                True,
                True,
                False,
                True,
                snapshot.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED,
                _new_entry_allowed(snapshot),
                LossLimitRuntimeCoordinationFailure(
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "checkpoint result invalid",
                ),
                snapshot.save_triggers,
            )
        status = (
            RuntimeCoordinationStatus.IDEMPOTENT
            if successful and runtime_status == "IDEMPOTENT"
            else RuntimeCoordinationStatus.SUCCEEDED
            if successful
            else RuntimeCoordinationStatus.PARTIAL
        )
        return LossLimitRuntimeCoordinationResult(
            status,
            operation,
            runtime_status,
            result.status,
            snapshot,
            True,
            True,
            True,
            successful,
            not successful,
            snapshot.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED,
            _new_entry_allowed(snapshot),
            None
            if successful
            else LossLimitRuntimeCoordinationFailure(
                RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_CHECKPOINT_FAILED,
                "checkpoint failed",
            ),
            snapshot.save_triggers,
        )

    def startup(self, request):
        operation = RuntimeOperationType.STARTUP
        if not isinstance(request, LossLimitRuntimeStartupRequest):
            return self._failed(
                operation,
                RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_REQUEST_INVALID,
                "invalid startup request",
            )
        with self._lock:
            try:
                result = self._startup.start(request)
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_STARTUP_FAILED,
                    "startup failed",
                )
            if not isinstance(result, LossLimitRuntimeStartupCoordinationResult):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "startup result invalid",
                )
            if result.status is StartupCoordinationStatus.FAILED:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_STARTUP_FAILED,
                    "startup failed",
                    result.snapshot,
                    result.status.value,
                )
            if not isinstance(result.snapshot, LossLimitRuntimeSnapshot):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "startup result invalid",
                )
            if result.status is StartupCoordinationStatus.RECOVERY_REQUIRED:
                return self._without_checkpoint(
                    operation,
                    result.status.value,
                    result.snapshot,
                    RuntimeCoordinationStatus.RECOVERY_REQUIRED,
                )
            try:
                policy = build_loss_limit_checkpoint_policy_decision(
                    operation,
                    result.status.value,
                    result.snapshot,
                    result.save_required,
                    result.save_triggers,
                )
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_CHECKPOINT_POLICY_INVALID,
                    "checkpoint policy invalid",
                    result.snapshot,
                    result.status.value,
                )
            if not policy.required:
                status = (
                    RuntimeCoordinationStatus.IDEMPOTENT
                    if result.status is StartupCoordinationStatus.IDEMPOTENT
                    else RuntimeCoordinationStatus.SUCCEEDED
                )
                return self._without_checkpoint(
                    operation, result.status.value, result.snapshot, status
                )
            return self._with_checkpoint(
                operation,
                result.status.value,
                result.snapshot,
                policy,
                request.received_at,
            )

    def apply_update(self, request):
        operation = RuntimeOperationType.UPDATE
        if not isinstance(request, LossLimitRuntimeUpdate):
            return self._failed(
                operation,
                RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_REQUEST_INVALID,
                "invalid update request",
            )
        with self._lock:
            try:
                result = self._store.apply_update(request)
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_UPDATE_FAILED,
                    "runtime update failed",
                )
            if not isinstance(result, LossLimitRuntimeStoreResult):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "runtime update result invalid",
                )
            if result.status is StoreResultStatus.FAILED:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_UPDATE_FAILED,
                    "runtime update failed",
                    None,
                    result.status.value,
                )
            if not isinstance(result.snapshot, LossLimitRuntimeSnapshot):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "runtime update result invalid",
                )
            try:
                policy = build_loss_limit_checkpoint_policy_decision(
                    operation,
                    result.status.value,
                    result.snapshot,
                    result.save_required,
                    result.snapshot.save_triggers,
                )
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_CHECKPOINT_POLICY_INVALID,
                    "checkpoint policy invalid",
                    result.snapshot,
                    result.status.value,
                )
            if not policy.required:
                status = (
                    RuntimeCoordinationStatus.IDEMPOTENT
                    if result.status is StoreResultStatus.IDEMPOTENT
                    else RuntimeCoordinationStatus.SUCCEEDED
                )
                return self._without_checkpoint(
                    operation, result.status.value, result.snapshot, status
                )
            return self._with_checkpoint(
                operation,
                result.status.value,
                result.snapshot,
                policy,
                request.occurred_at,
            )

    def stop(self, request):
        operation = RuntimeOperationType.STOP
        if not isinstance(request, LossLimitRuntimeStopRequest):
            return self._failed(
                operation,
                RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_REQUEST_INVALID,
                "invalid stop request",
            )
        with self._lock:
            try:
                before = self._store.get_snapshot()
                if (
                    not isinstance(before, LossLimitRuntimeStoreResult)
                    or before.status is not StoreResultStatus.SUCCEEDED
                    or before.snapshot.sequence != request.expected_sequence
                ):
                    return self._failed(
                        operation,
                        RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_STOP_FAILED,
                        "runtime stop failed",
                    )
                result = self._store.stop(request.occurred_at, request.expected_revision)
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_STOP_FAILED,
                    "runtime stop failed",
                )
            if (
                not isinstance(result, LossLimitRuntimeStoreResult)
                or result.status is StoreResultStatus.FAILED
            ):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_STOP_FAILED,
                    "runtime stop failed",
                    None,
                    result.status.value
                    if isinstance(result, LossLimitRuntimeStoreResult)
                    else None,
                )
            snapshot = result.snapshot
            if (
                not isinstance(snapshot, LossLimitRuntimeSnapshot)
                or snapshot.lifecycle is not RuntimeLifecycle.STOPPED
            ):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_RESULT_INVALID,
                    "runtime stop result invalid",
                )
            try:
                policy = build_loss_limit_checkpoint_policy_decision(
                    operation,
                    result.status.value,
                    snapshot,
                    result.save_required,
                    snapshot.save_triggers,
                )
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_CHECKPOINT_POLICY_INVALID,
                    "checkpoint policy invalid",
                    snapshot,
                    result.status.value,
                )
            return self._with_checkpoint(
                operation,
                result.status.value,
                snapshot,
                policy,
                request.requested_at,
            )

    def checkpoint(self, request):
        operation = RuntimeOperationType.MANUAL_CHECKPOINT
        if not isinstance(request, LossLimitRuntimeCheckpointRequest):
            return self._failed(
                operation,
                RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_REQUEST_INVALID,
                "invalid checkpoint request",
            )
        if request.checkpoint_mode is not CheckpointMode.MANUAL:
            return self._failed(
                operation,
                RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_REQUEST_INVALID,
                "manual checkpoint required",
            )
        with self._lock:
            try:
                snapshot_result = self._store.get_snapshot()
            except Exception:
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_INTERNAL_FAILURE,
                    "checkpoint unavailable",
                )
            if (
                not isinstance(snapshot_result, LossLimitRuntimeStoreResult)
                or snapshot_result.status is not StoreResultStatus.SUCCEEDED
                or not isinstance(snapshot_result.snapshot, LossLimitRuntimeSnapshot)
            ):
                return self._failed(
                    operation,
                    RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_CHECKPOINT_FAILED,
                    "checkpoint unavailable",
                )
            policy = type("_Policy", (), {"trigger": request.trigger})()
            return self._with_checkpoint(
                operation,
                "SUCCEEDED",
                snapshot_result.snapshot,
                policy,
                request.requested_at,
                request,
            )
