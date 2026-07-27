"""MM-4K projection-only final gate for new execution entries."""

from threading import RLock

from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
)
from .loss_application_registration import MoneyManagementApplicationRegistration
from .loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionGuardReason,
    LossExecutionGuardRequest,
    LossExecutionGuardResult,
    LossGovernanceProjectionReadResult,
    LossGovernanceProjectionReadStatus,
)
from .loss_governance_projection_dispatcher import (
    get_money_management_governance_projection,
)
from .loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernancePublicSnapshot,
)


def _read_failure(status, reason):
    return LossGovernanceProjectionReadResult(status, None, (reason,))


class LossGovernanceProjectionReader:
    """Reads only immutable application-state contracts."""

    def __init__(self):
        self._lock = RLock()

    def read(self, app):
        with self._lock:
            try:
                state = getattr(app, "state", None)
                registration_before = getattr(state, "money_management", None)
                if not isinstance(
                    registration_before, MoneyManagementApplicationRegistration
                ):
                    return _read_failure(
                        LossGovernanceProjectionReadStatus.REGISTRATION_UNAVAILABLE,
                        "money management registration unavailable",
                    )
                if (
                    registration_before.composition_status
                    is not CompositionReadinessStatus.READY
                ):
                    return _read_failure(
                        LossGovernanceProjectionReadStatus.REGISTRATION_UNAVAILABLE,
                        "money management registration unavailable",
                    )
                safe_status = registration_before.safe_status
                if (
                    safe_status.lifecycle_state
                    is not ApplicationLifecycleState.RUNNING
                    or not safe_status.runtime_available
                    or safe_status.recovery_required
                ):
                    return _read_failure(
                        LossGovernanceProjectionReadStatus.LIFECYCLE_NOT_RUNNING,
                        "money management lifecycle not running",
                    )
                projection_before = get_money_management_governance_projection(app)
                if projection_before is None:
                    return _read_failure(
                        LossGovernanceProjectionReadStatus.PROJECTION_MISSING,
                        "money management projection unavailable",
                    )
                registration_after = getattr(state, "money_management", None)
                projection_after = get_money_management_governance_projection(app)
                if (
                    registration_after is not registration_before
                    or projection_after is not projection_before
                    or not isinstance(
                        projection_after, LossGovernancePublicSnapshot
                    )
                    or projection_after.revision is None
                    or projection_after.sequence is None
                ):
                    return _read_failure(
                        LossGovernanceProjectionReadStatus.PROJECTION_INVALID,
                        "money management projection invalid",
                    )
                if (
                    safe_status.revision is not None
                    and safe_status.sequence is not None
                    and (
                        projection_after.revision < safe_status.revision
                        or projection_after.sequence < safe_status.sequence
                    )
                ):
                    return _read_failure(
                        LossGovernanceProjectionReadStatus.PROJECTION_INVALID,
                        "money management projection revision invalid",
                    )
                return LossGovernanceProjectionReadResult(
                    LossGovernanceProjectionReadStatus.AVAILABLE,
                    projection_after,
                    (),
                )
            except Exception:
                return _read_failure(
                    LossGovernanceProjectionReadStatus.PROJECTION_INVALID,
                    "money management projection read failed",
                )


def _guard_result(
    request,
    decision,
    reason,
    revision=None,
    sequence=None,
):
    return LossExecutionGuardResult(
        request.operation,
        decision,
        decision is LossExecutionEntryDecision.ALLOW,
        reason.value if hasattr(reason, "value") else str(reason),
        request.requested_at,
        revision,
        sequence,
    )


class LossExecutionEntryGuardDispatcher:
    """Returns a decision only; it never invokes or mutates execution."""

    def __init__(self, projection_reader=None):
        self._reader = projection_reader or LossGovernanceProjectionReader()
        if not isinstance(self._reader, LossGovernanceProjectionReader):
            raise TypeError("projection reader required")
        self._lock = RLock()

    def dispatch(self, app, request):
        if not isinstance(request, LossExecutionGuardRequest):
            raise TypeError("execution guard request required")
        # Close/reduction/cancel operations are deliberately outside the loss
        # entry gate and must pass even when Money Management is unavailable.
        if not request.operation.is_new_entry:
            return _guard_result(
                request,
                LossExecutionEntryDecision.ALLOW,
                LossExecutionGuardReason.OPERATION_NOT_GUARDED,
            )
        with self._lock:
            try:
                read_result = self._reader.read(app)
                if not isinstance(
                    read_result, LossGovernanceProjectionReadResult
                ):
                    return _guard_result(
                        request,
                        LossExecutionEntryDecision.UNKNOWN,
                        LossExecutionGuardReason.PROJECTION_INVALID,
                    )
                if (
                    read_result.status
                    is not LossGovernanceProjectionReadStatus.AVAILABLE
                ):
                    reason = {
                        LossGovernanceProjectionReadStatus.REGISTRATION_UNAVAILABLE:
                            LossExecutionGuardReason.REGISTRATION_UNAVAILABLE,
                        LossGovernanceProjectionReadStatus.LIFECYCLE_NOT_RUNNING:
                            LossExecutionGuardReason.LIFECYCLE_NOT_RUNNING,
                        LossGovernanceProjectionReadStatus.PROJECTION_MISSING:
                            LossExecutionGuardReason.PROJECTION_MISSING,
                        LossGovernanceProjectionReadStatus.PROJECTION_INVALID:
                            LossExecutionGuardReason.PROJECTION_INVALID,
                    }[read_result.status]
                    return _guard_result(
                        request,
                        LossExecutionEntryDecision.UNKNOWN,
                        reason,
                    )
                public_snapshot = read_result.public_snapshot
                if (
                    request.expected_revision is not None
                    and (
                        request.expected_revision != public_snapshot.revision
                        or request.expected_sequence != public_snapshot.sequence
                    )
                ):
                    return _guard_result(
                        request,
                        LossExecutionEntryDecision.UNKNOWN,
                        LossExecutionGuardReason.PROJECTION_REVISION_MISMATCH,
                        public_snapshot.revision,
                        public_snapshot.sequence,
                    )
                if public_snapshot.generated_at > request.requested_at:
                    return _guard_result(
                        request,
                        LossExecutionEntryDecision.UNKNOWN,
                        LossExecutionGuardReason.PROJECTION_TIMESTAMP_INVALID,
                        public_snapshot.revision,
                        public_snapshot.sequence,
                    )
                if (
                    request.requested_at - public_snapshot.generated_at
                    > request.maximum_projection_age
                ):
                    return _guard_result(
                        request,
                        LossExecutionEntryDecision.UNKNOWN,
                        LossExecutionGuardReason.PROJECTION_TIMESTAMP_INVALID,
                        public_snapshot.revision,
                        public_snapshot.sequence,
                    )
                projection = public_snapshot.projection
                decision = LossExecutionEntryDecision(
                    projection.entry_permission.value
                )
                if projection.entry_permission is LossEntryPermission.ALLOW:
                    reason = LossExecutionGuardReason.ENTRY_ALLOWED
                else:
                    reason = (
                        projection.block_reason
                        if projection.block_reason is not None
                        else LossExecutionGuardReason.PROJECTION_INVALID
                    )
                if (
                    projection.entry_permission is not LossEntryPermission.ALLOW
                    and reason is LossExecutionGuardReason.PROJECTION_INVALID
                ):
                    decision = LossExecutionEntryDecision.UNKNOWN
                return _guard_result(
                    request,
                    decision,
                    reason,
                    public_snapshot.revision,
                    public_snapshot.sequence,
                )
            except Exception:
                return _guard_result(
                    request,
                    LossExecutionEntryDecision.UNKNOWN,
                    LossExecutionGuardReason.INTERNAL_FAILURE,
                )


def dispatch_money_management_execution_entry_guard(app, dispatcher, request):
    if not isinstance(dispatcher, LossExecutionEntryGuardDispatcher):
        if not isinstance(request, LossExecutionGuardRequest):
            raise TypeError("execution guard request required")
        if not request.operation.is_new_entry:
            return _guard_result(
                request,
                LossExecutionEntryDecision.ALLOW,
                LossExecutionGuardReason.OPERATION_NOT_GUARDED,
            )
        return _guard_result(
            request,
            LossExecutionEntryDecision.UNKNOWN,
            LossExecutionGuardReason.INTERNAL_FAILURE,
        )
    return dispatcher.dispatch(app, request)
