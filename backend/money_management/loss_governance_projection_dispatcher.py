"""MM-4J application-scoped governance projection dispatcher."""

from datetime import datetime, timezone
from threading import RLock

from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LossLimitApplicationStatus,
)
from .loss_application_registration import MoneyManagementApplicationRegistration
from .loss_governance_projection import build_loss_governance_projection
from .loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceBoundaryReason,
    LossGovernanceProjection,
    LossGovernanceProjectionBuildInput,
    LossGovernanceProjectionDispatchResult,
    LossGovernanceProjectionDispatchStatus,
    LossGovernancePublicSnapshot,
)
from .loss_reason_models import DiagnosticReason
from .loss_runtime_integration_models import GovernanceProjection
from .loss_runtime_store_models import LossLimitRuntimeSnapshot


APPLICATION_STATE_ATTRIBUTE = "money_management_governance_projection"


def get_money_management_governance_projection(app):
    state = getattr(app, "state", None)
    value = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    return value if isinstance(value, LossGovernancePublicSnapshot) else None


def _unknown_projection(generated_at):
    return LossGovernanceProjection(
        LossEntryPermission.UNKNOWN,
        False,
        LossGovernanceBoundaryReason.UNKNOWN_STATE,
        None,
        None,
        False,
        (DiagnosticReason.METRIC_UNAVAILABLE,),
        generated_at,
    )


def _recovery_projection(generated_at):
    return LossGovernanceProjection(
        LossEntryPermission.RECOVERY_REQUIRED,
        False,
        LossGovernanceBoundaryReason.RECOVERY_REQUIRED,
        None,
        GovernanceProjection.RECOVERY_REQUIRED,
        True,
        (DiagnosticReason.METRIC_UNAVAILABLE,),
        generated_at,
    )


class LossGovernanceProjectionDispatcher:
    def __init__(
        self,
        projection_builder=build_loss_governance_projection,
        timestamp_source=None,
    ):
        if not callable(projection_builder):
            raise TypeError("projection builder required")
        self._builder = projection_builder
        self._timestamp_source = timestamp_source or (
            lambda: datetime.now(timezone.utc)
        )
        if not callable(self._timestamp_source):
            raise TypeError("timestamp source required")
        self._lock = RLock()

    def _publish(self, app, projection, revision, sequence, reasons, fail_closed):
        public_snapshot = LossGovernancePublicSnapshot(
            projection,
            revision,
            sequence,
            projection.generated_at,
        )
        existing = get_money_management_governance_projection(app)
        if existing is not None and existing.to_dict() == public_snapshot.to_dict():
            return LossGovernanceProjectionDispatchResult(
                LossGovernanceProjectionDispatchStatus.IDEMPOTENT,
                existing,
                False,
                tuple(reasons),
            )
        state = getattr(app, "state", None)
        if state is not None:
            setattr(state, APPLICATION_STATE_ATTRIBUTE, public_snapshot)
        return LossGovernanceProjectionDispatchResult(
            LossGovernanceProjectionDispatchStatus.FAIL_CLOSED
            if fail_closed
            else LossGovernanceProjectionDispatchStatus.PROJECTED,
            public_snapshot,
            True,
            tuple(reasons),
        )

    def _fallback_timestamp(self, app, revision, sequence):
        existing = get_money_management_governance_projection(app)
        if (
            existing is not None
            and existing.revision == revision
            and existing.sequence == sequence
            and existing.projection.entry_permission
            in (
                LossEntryPermission.UNKNOWN,
                LossEntryPermission.RECOVERY_REQUIRED,
            )
        ):
            return existing.generated_at
        value = self._timestamp_source()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise TypeError("timestamp source returned invalid value")
        return value.astimezone(timezone.utc)

    def _fail_closed(self, app, reason, revision=None, sequence=None):
        generated_at = self._fallback_timestamp(app, revision, sequence)
        return self._publish(
            app,
            _unknown_projection(generated_at),
            revision,
            sequence,
            (reason,),
            True,
        )

    def dispatch(self, app):
        with self._lock:
            try:
                state = getattr(app, "state", None)
                registration = getattr(state, "money_management", None)
                if not isinstance(
                    registration, MoneyManagementApplicationRegistration
                ):
                    return self._fail_closed(
                        app, "money management registration unavailable"
                    )
                if (
                    registration.composition_status
                    is not CompositionReadinessStatus.READY
                ):
                    if (
                        registration.composition_status
                        is CompositionReadinessStatus.RECOVERY_REQUIRED
                    ):
                        generated_at = self._fallback_timestamp(app, None, None)
                        return self._publish(
                            app,
                            _recovery_projection(generated_at),
                            None,
                            None,
                            ("money management recovery required",),
                            True,
                        )
                    return self._fail_closed(
                        app, "money management unavailable"
                    )
                lifecycle = registration.lifecycle_adapter
                if lifecycle is None:
                    return self._fail_closed(app, "lifecycle adapter unavailable")
                lifecycle_status = lifecycle.get_status()
                if not isinstance(lifecycle_status, LossLimitApplicationStatus):
                    return self._fail_closed(app, "lifecycle status invalid")
                revision = lifecycle_status.revision
                sequence = lifecycle_status.sequence
                if (
                    lifecycle_status.lifecycle_state
                    is ApplicationLifecycleState.RECOVERY_REQUIRED
                ):
                    generated_at = self._fallback_timestamp(
                        app, revision, sequence
                    )
                    return self._publish(
                        app,
                        _recovery_projection(generated_at),
                        revision,
                        sequence,
                        ("loss runtime recovery required",),
                        True,
                    )
                if (
                    lifecycle_status.lifecycle_state
                    is not ApplicationLifecycleState.RUNNING
                ):
                    return self._fail_closed(
                        app,
                        "lifecycle not running",
                        revision,
                        sequence,
                    )
                runtime_snapshot = lifecycle.get_snapshot()
                if not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot):
                    return self._fail_closed(
                        app,
                        "runtime snapshot unavailable",
                        revision,
                        sequence,
                    )
                if (
                    runtime_snapshot.revision != revision
                    or runtime_snapshot.sequence != sequence
                ):
                    return self._fail_closed(
                        app,
                        "runtime state inconsistent",
                        revision,
                        sequence,
                    )
                decision = (
                    runtime_snapshot.state.last_decision
                    if runtime_snapshot.state is not None
                    else None
                )
                projection = self._builder(
                    LossGovernanceProjectionBuildInput(
                        decision,
                        runtime_snapshot.governance_projection,
                        runtime_snapshot.recovery_requirement.required,
                        runtime_snapshot.updated_at,
                    )
                )
                if not isinstance(projection, LossGovernanceProjection):
                    return self._fail_closed(
                        app,
                        "governance projection invalid",
                        revision,
                        sequence,
                    )
                fail_closed = projection.entry_permission in (
                    LossEntryPermission.UNKNOWN,
                    LossEntryPermission.RECOVERY_REQUIRED,
                )
                return self._publish(
                    app,
                    projection,
                    revision,
                    sequence,
                    ()
                    if not fail_closed
                    else ("governance projection fail closed",),
                    fail_closed,
                )
            except Exception:
                try:
                    return self._fail_closed(
                        app, "governance projection failed"
                    )
                except Exception:
                    generated_at = datetime.now(timezone.utc)
                    snapshot = LossGovernancePublicSnapshot(
                        _unknown_projection(generated_at),
                        None,
                        None,
                        generated_at,
                    )
                    return LossGovernanceProjectionDispatchResult(
                        LossGovernanceProjectionDispatchStatus.FAIL_CLOSED,
                        snapshot,
                        True,
                        ("governance projection failed",),
                    )


def dispatch_money_management_governance_projection(app, dispatcher):
    if not isinstance(dispatcher, LossGovernanceProjectionDispatcher):
        generated_at = datetime.now(timezone.utc)
        snapshot = LossGovernancePublicSnapshot(
            _unknown_projection(generated_at),
            None,
            None,
            generated_at,
        )
        return LossGovernanceProjectionDispatchResult(
            LossGovernanceProjectionDispatchStatus.FAIL_CLOSED,
            snapshot,
            True,
            ("governance projection dispatcher invalid",),
        )
    return dispatcher.dispatch(app)
