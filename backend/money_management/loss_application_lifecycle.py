"""MM-4F application-facing lifecycle adapter."""
from threading import RLock

from .loss_application_models import (
    ApplicationFailureCode,
    ApplicationLifecycleState,
    LifecycleOperationStatus,
    LossLimitApplicationFailure,
    LossLimitApplicationStatus,
    LossLimitCompositionReadiness,
    LossLimitLifecycleOperationResult,
)
from .loss_runtime_checkpoint_models import LossLimitRuntimeCheckpointRequest
from .loss_runtime_coordination_models import (
    LossLimitRuntimeCoordinationResult,
    LossLimitRuntimeStopRequest,
    RuntimeCoordinationStatus,
)
from .loss_runtime_startup_models import LossLimitRuntimeStartupRequest
from .loss_runtime_store_models import (
    LossLimitRuntimeUpdate,
    StoreResultStatus,
)


class LossLimitApplicationLifecycleAdapter:
    def __init__(self, runtime_coordinator, runtime_store, readiness):
        if runtime_coordinator is None or runtime_store is None:
            raise TypeError("runtime coordinator and store required")
        if not isinstance(readiness, LossLimitCompositionReadiness):
            raise TypeError("readiness required")
        self._runtime_coordinator = runtime_coordinator
        self._runtime_store = runtime_store
        self._readiness = readiness
        self._state = ApplicationLifecycleState.CREATED
        self._last_startup_result = None
        self._last_operation_result = None
        self._last_shutdown_result = None
        self._lock = RLock()

    @property
    def lifecycle_state(self):
        with self._lock:
            return self._state

    @staticmethod
    def _failure(state, message, code=ApplicationFailureCode.LOSS_APPLICATION_OPERATION_FAILED):
        return LossLimitLifecycleOperationResult(
            LifecycleOperationStatus.FAILED,
            state,
            None,
            LossLimitApplicationFailure(code, message),
        )

    @staticmethod
    def _rejected(state, message):
        return LossLimitLifecycleOperationResult(
            LifecycleOperationStatus.REJECTED,
            state,
            None,
            LossLimitApplicationFailure(
                ApplicationFailureCode.LOSS_APPLICATION_LIFECYCLE_INVALID, message
            ),
        )

    @staticmethod
    def _project(coordination, state):
        if not isinstance(coordination, LossLimitRuntimeCoordinationResult):
            return LossLimitApplicationLifecycleAdapter._failure(
                ApplicationLifecycleState.FAILED,
                "runtime coordination result invalid",
                ApplicationFailureCode.LOSS_APPLICATION_CHILD_RESULT_INVALID,
            )
        status = {
            RuntimeCoordinationStatus.SUCCEEDED: LifecycleOperationStatus.SUCCEEDED,
            RuntimeCoordinationStatus.IDEMPOTENT: LifecycleOperationStatus.IDEMPOTENT,
            RuntimeCoordinationStatus.PARTIAL: LifecycleOperationStatus.PARTIAL,
            RuntimeCoordinationStatus.DURABILITY_PENDING: LifecycleOperationStatus.PARTIAL,
            RuntimeCoordinationStatus.RECOVERY_REQUIRED: LifecycleOperationStatus.RECOVERY_REQUIRED,
            RuntimeCoordinationStatus.FAILED: LifecycleOperationStatus.FAILED,
        }[coordination.status]
        failure = None
        if status is LifecycleOperationStatus.FAILED:
            failure = LossLimitApplicationFailure(
                ApplicationFailureCode.LOSS_APPLICATION_OPERATION_FAILED,
                "runtime operation failed",
            )
        return LossLimitLifecycleOperationResult(status, state, coordination, failure)

    def startup(self, request):
        if not isinstance(request, LossLimitRuntimeStartupRequest):
            return self._rejected(self.lifecycle_state, "invalid startup request")
        with self._lock:
            if self._state is not ApplicationLifecycleState.CREATED:
                if self._last_startup_result is not None:
                    return LossLimitLifecycleOperationResult(
                        LifecycleOperationStatus.IDEMPOTENT,
                        self._state,
                        self._last_startup_result.coordination_result,
                        None,
                    )
                return self._rejected(self._state, "startup not allowed")
            self._state = ApplicationLifecycleState.STARTING
            try:
                coordination = self._runtime_coordinator.startup(request)
            except Exception:
                self._state = ApplicationLifecycleState.FAILED
                result = self._failure(self._state, "application startup failed")
                self._last_startup_result = result
                self._last_operation_result = result
                return result
            if not isinstance(coordination, LossLimitRuntimeCoordinationResult):
                self._state = ApplicationLifecycleState.FAILED
                result = self._failure(
                    self._state,
                    "runtime coordination result invalid",
                    ApplicationFailureCode.LOSS_APPLICATION_CHILD_RESULT_INVALID,
                )
            elif coordination.recovery_required:
                self._state = ApplicationLifecycleState.RECOVERY_REQUIRED
                result = self._project(coordination, self._state)
            elif coordination.status is RuntimeCoordinationStatus.FAILED:
                self._state = ApplicationLifecycleState.FAILED
                result = self._project(coordination, self._state)
            else:
                self._state = ApplicationLifecycleState.RUNNING
                result = self._project(coordination, self._state)
            self._last_startup_result = result
            self._last_operation_result = result
            return result

    def apply_update(self, request):
        if not isinstance(request, LossLimitRuntimeUpdate):
            return self._rejected(self.lifecycle_state, "invalid update request")
        with self._lock:
            if self._state is not ApplicationLifecycleState.RUNNING:
                return self._rejected(self._state, "runtime update not allowed")
            try:
                coordination = self._runtime_coordinator.apply_update(request)
            except Exception:
                result = self._failure(self._state, "runtime update failed")
                self._last_operation_result = result
                return result
            if not isinstance(coordination, LossLimitRuntimeCoordinationResult):
                self._state = ApplicationLifecycleState.FAILED
                result = self._failure(
                    self._state,
                    "runtime coordination result invalid",
                    ApplicationFailureCode.LOSS_APPLICATION_CHILD_RESULT_INVALID,
                )
            else:
                if coordination.recovery_required:
                    self._state = ApplicationLifecycleState.RECOVERY_REQUIRED
                result = self._project(coordination, self._state)
            self._last_operation_result = result
            return result

    def manual_checkpoint(self, request):
        if not isinstance(request, LossLimitRuntimeCheckpointRequest):
            return self._rejected(self.lifecycle_state, "invalid checkpoint request")
        with self._lock:
            if self._state not in (
                ApplicationLifecycleState.RUNNING,
                ApplicationLifecycleState.RECOVERY_REQUIRED,
                ApplicationLifecycleState.STOPPED,
            ):
                return self._rejected(self._state, "manual checkpoint not allowed")
            try:
                coordination = self._runtime_coordinator.checkpoint(request)
            except Exception:
                result = self._failure(self._state, "manual checkpoint failed")
                self._last_operation_result = result
                return result
            result = self._project(coordination, self._state)
            self._last_operation_result = result
            return result

    def shutdown(self, request):
        if not isinstance(request, LossLimitRuntimeStopRequest):
            return self._rejected(self.lifecycle_state, "invalid shutdown request")
        with self._lock:
            if self._state is ApplicationLifecycleState.STOPPED:
                return LossLimitLifecycleOperationResult(
                    LifecycleOperationStatus.IDEMPOTENT,
                    self._state,
                    self._last_shutdown_result.coordination_result
                    if self._last_shutdown_result
                    else None,
                    None,
                )
            if self._state is ApplicationLifecycleState.CREATED:
                self._state = ApplicationLifecycleState.STOPPED
                result = LossLimitLifecycleOperationResult(
                    LifecycleOperationStatus.SUCCEEDED, self._state, None, None
                )
                self._last_shutdown_result = result
                self._last_operation_result = result
                return result
            if self._state in (
                ApplicationLifecycleState.STARTING,
                ApplicationLifecycleState.STOPPING,
            ):
                return self._rejected(self._state, "shutdown not allowed")
            self._state = ApplicationLifecycleState.STOPPING
            try:
                coordination = self._runtime_coordinator.stop(request)
            except Exception:
                self._state = ApplicationLifecycleState.FAILED
                result = self._failure(self._state, "application shutdown failed")
            else:
                snapshot = (
                    coordination.snapshot
                    if isinstance(coordination, LossLimitRuntimeCoordinationResult)
                    else None
                )
                if snapshot is not None and snapshot.lifecycle.value == "STOPPED":
                    self._state = ApplicationLifecycleState.STOPPED
                else:
                    self._state = ApplicationLifecycleState.FAILED
                result = self._project(coordination, self._state)
            self._last_shutdown_result = result
            self._last_operation_result = result
            return result

    def get_snapshot(self):
        with self._lock:
            try:
                result = self._runtime_store.get_snapshot()
            except Exception:
                return None
            return (
                result.snapshot
                if result.status is StoreResultStatus.SUCCEEDED
                else None
            )

    def get_status(self):
        with self._lock:
            snapshot = self.get_snapshot()
            coordination = (
                self._last_operation_result.coordination_result
                if self._last_operation_result is not None
                else None
            )
            available = self._state is ApplicationLifecycleState.RUNNING
            recovery = self._state is ApplicationLifecycleState.RECOVERY_REQUIRED
            return LossLimitApplicationStatus(
                self._state,
                self._readiness.status,
                available,
                snapshot.lifecycle if snapshot else None,
                bool(
                    available
                    and coordination is not None
                    and coordination.new_entry_allowed
                ),
                recovery
                or bool(coordination is not None and coordination.recovery_required),
                bool(coordination is not None and coordination.durability_pending),
                snapshot.revision if snapshot else None,
                snapshot.sequence if snapshot else None,
                self._last_operation_result.status.value
                if self._last_operation_result
                else None,
                coordination.checkpoint_result_status if coordination else None,
            )
