"""MM-4I explicit, application-scoped runtime update dispatcher."""

import json
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Optional, Tuple

from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LifecycleOperationStatus,
    LossLimitApplicationStatus,
    LossLimitLifecycleOperationResult,
)
from .loss_application_registration import MoneyManagementApplicationRegistration
from .loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
    LossRuntimeEvaluationStatus,
)
from .loss_runtime_event_adapter import LossRuntimeEventAdapter
from .loss_runtime_event_models import (
    LossRuntimeEvent,
    LossRuntimeEventAdapterStatus,
    LossRuntimeEventFailureCode,
    LossRuntimeEventType,
)
from .loss_runtime_metrics_models import (
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
)
from .loss_runtime_metrics_source import LossRuntimeMetricsSource
from .loss_runtime_store_models import LossLimitRuntimeSnapshot


class LossRuntimeDispatchStatus(str, Enum):
    DISABLED = "DISABLED"
    APPLIED = "APPLIED"
    IDEMPOTENT = "IDEMPOTENT"
    REJECTED = "REJECTED"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    UNAVAILABLE = "UNAVAILABLE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class LossRuntimeDispatchResult:
    status: LossRuntimeDispatchStatus
    event_status: Optional[str]
    lifecycle_status: Optional[str]
    runtime_revision: Optional[int]
    runtime_sequence: Optional[int]
    durability_pending: bool
    safe_reasons: Tuple[str, ...]
    applied: bool
    new_entry_allowed: bool

    def __post_init__(self):
        object.__setattr__(self, "status", LossRuntimeDispatchStatus(self.status))
        for name in ("durability_pending", "applied", "new_entry_allowed"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")
        object.__setattr__(
            self, "safe_reasons", tuple(str(item) for item in self.safe_reasons)
        )
        if not self.applied and self.new_entry_allowed:
            raise ValueError("failed dispatch cannot allow new entries")

    def to_dict(self):
        return {
            "status": self.status.value,
            "eventStatus": self.event_status,
            "lifecycleStatus": self.lifecycle_status,
            "runtimeRevision": self.runtime_revision,
            "runtimeSequence": self.runtime_sequence,
            "durabilityPending": self.durability_pending,
            "safeReasons": list(self.safe_reasons),
            "applied": self.applied,
            "newEntryAllowed": self.new_entry_allowed,
        }


def _result(
    status,
    reason=(),
    *,
    event_status=None,
    lifecycle_status=None,
    snapshot=None,
    durability_pending=False,
    applied=False,
    new_entry_allowed=False,
):
    return LossRuntimeDispatchResult(
        status,
        event_status,
        lifecycle_status,
        snapshot.revision if isinstance(snapshot, LossLimitRuntimeSnapshot) else None,
        snapshot.sequence if isinstance(snapshot, LossLimitRuntimeSnapshot) else None,
        durability_pending,
        tuple(reason),
        applied,
        new_entry_allowed if applied else False,
    )


def _event_failure_status(code):
    if code is LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_CONFLICT:
        return LossRuntimeDispatchStatus.CONFLICT
    if code in (
        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_STALE,
        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_TIMESTAMP_INVALID,
    ):
        return LossRuntimeDispatchStatus.STALE
    return LossRuntimeDispatchStatus.REJECTED


def _lifecycle_projection(result, snapshot):
    if not isinstance(result, LossLimitLifecycleOperationResult):
        return _result(
            LossRuntimeDispatchStatus.FAILED,
            ("lifecycle result invalid",),
            snapshot=snapshot,
        )
    coordination = result.coordination_result
    pending = bool(
        coordination is not None and coordination.durability_pending
    )
    entries = bool(
        coordination is not None and coordination.new_entry_allowed
    )
    status = result.status
    if status in (
        LifecycleOperationStatus.SUCCEEDED,
        LifecycleOperationStatus.PARTIAL,
    ):
        return _result(
            LossRuntimeDispatchStatus.APPLIED,
            (),
            lifecycle_status=status.value,
            snapshot=snapshot,
            durability_pending=pending
            or status is LifecycleOperationStatus.PARTIAL,
            applied=True,
            new_entry_allowed=entries,
        )
    if status is LifecycleOperationStatus.IDEMPOTENT:
        return _result(
            LossRuntimeDispatchStatus.IDEMPOTENT,
            (),
            lifecycle_status=status.value,
            snapshot=snapshot,
        )
    if status is LifecycleOperationStatus.RECOVERY_REQUIRED:
        return _result(
            LossRuntimeDispatchStatus.RECOVERY_REQUIRED,
            ("loss runtime recovery required",),
            lifecycle_status=status.value,
            snapshot=snapshot,
            durability_pending=pending,
        )
    if status is LifecycleOperationStatus.REJECTED:
        return _result(
            LossRuntimeDispatchStatus.REJECTED,
            ("lifecycle update rejected",),
            lifecycle_status=status.value,
            snapshot=snapshot,
        )
    return _result(
        LossRuntimeDispatchStatus.FAILED,
        ("lifecycle update failed",),
        lifecycle_status=status.value,
        snapshot=snapshot,
        durability_pending=pending,
    )


class LossRuntimeUpdateDispatcher:
    """Serializes one application's metrics-to-lifecycle update stream."""

    def __init__(self, metrics_source, evaluation_bridge=None, event_adapter=None):
        if not isinstance(metrics_source, LossRuntimeMetricsSource):
            raise TypeError("runtime metrics source required")
        self._metrics_source = metrics_source
        self._evaluation_bridge = evaluation_bridge or LossRuntimeEvaluationBridge()
        self._event_adapter = event_adapter or LossRuntimeEventAdapter()
        if not isinstance(self._evaluation_bridge, LossRuntimeEvaluationBridge):
            raise TypeError("runtime evaluation bridge required")
        if not isinstance(self._event_adapter, LossRuntimeEventAdapter):
            raise TypeError("runtime event adapter required")
        self._lock = RLock()
        self._last_event_id = None
        self._last_metrics_signature = None
        self._last_snapshot = None
        self._last_metrics_result = None

    def get_configuration(self):
        with self._lock:
            return self._evaluation_bridge.get_configuration()

    def replace_configuration(self, configuration):
        with self._lock:
            return self._evaluation_bridge.replace_configuration(configuration)

    def get_last_metrics_result(self):
        with self._lock:
            return self._last_metrics_result

    def reevaluate(self, app, request, event_type, reevaluation_token):
        if (
            not isinstance(reevaluation_token, str)
            or not reevaluation_token.strip()
        ):
            return _result(
                LossRuntimeDispatchStatus.REJECTED,
                ("reevaluation token invalid",),
            )
        return self.dispatch(
            app,
            request,
            event_type,
            cached_metrics=True,
            reevaluation_token=reevaluation_token.strip(),
        )

    def dispatch(
        self,
        app,
        request,
        event_type,
        *,
        cached_metrics=False,
        reevaluation_token=None,
    ):
        if not isinstance(request, LossRuntimeMetricsReadRequest):
            return _result(
                LossRuntimeDispatchStatus.FAILED,
                ("runtime metrics request invalid",),
            )
        try:
            event_type = LossRuntimeEventType(event_type)
        except (TypeError, ValueError):
            return _result(
                LossRuntimeDispatchStatus.REJECTED,
                ("runtime event type invalid",),
            )
        if type(cached_metrics) is not bool:
            return _result(
                LossRuntimeDispatchStatus.REJECTED,
                ("runtime metrics mode invalid",),
            )
        if reevaluation_token is not None and (
            not cached_metrics
            or not isinstance(reevaluation_token, str)
            or not reevaluation_token
        ):
            return _result(
                LossRuntimeDispatchStatus.REJECTED,
                ("reevaluation request invalid",),
            )
        with self._lock:
            try:
                registration = getattr(
                    getattr(app, "state", None),
                    "money_management",
                    None,
                )
                if not isinstance(
                    registration, MoneyManagementApplicationRegistration
                ):
                    return _result(
                        LossRuntimeDispatchStatus.UNAVAILABLE,
                        ("money management registration unavailable",),
                    )
                if (
                    registration.composition_status
                    is CompositionReadinessStatus.DISABLED
                ):
                    return _result(
                        LossRuntimeDispatchStatus.DISABLED,
                        ("money management disabled",),
                    )
                if (
                    registration.composition_status
                    is CompositionReadinessStatus.RECOVERY_REQUIRED
                ):
                    return _result(
                        LossRuntimeDispatchStatus.RECOVERY_REQUIRED,
                        ("money management recovery required",),
                    )
                lifecycle = registration.lifecycle_adapter
                if lifecycle is None:
                    return _result(
                        LossRuntimeDispatchStatus.UNAVAILABLE,
                        ("lifecycle adapter unavailable",),
                    )
                status = lifecycle.get_status()
                if not isinstance(status, LossLimitApplicationStatus):
                    return _result(
                        LossRuntimeDispatchStatus.FAILED,
                        ("lifecycle status invalid",),
                    )
                if status.lifecycle_state is not ApplicationLifecycleState.RUNNING:
                    target = (
                        LossRuntimeDispatchStatus.RECOVERY_REQUIRED
                        if status.lifecycle_state
                        is ApplicationLifecycleState.RECOVERY_REQUIRED
                        else LossRuntimeDispatchStatus.REJECTED
                    )
                    return _result(
                        target,
                        ("lifecycle not running",),
                    )
                runtime_snapshot = lifecycle.get_snapshot()
                if not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot):
                    return _result(
                        LossRuntimeDispatchStatus.UNAVAILABLE,
                        ("runtime snapshot unavailable",),
                    )
                metrics_result = (
                    self._last_metrics_result
                    if cached_metrics
                    else self._metrics_source.read_metrics(request)
                )
                if not isinstance(metrics_result, LossRuntimeMetricsReadResult):
                    return _result(
                        LossRuntimeDispatchStatus.FAILED,
                        ("runtime metrics result invalid",),
                        snapshot=runtime_snapshot,
                    )
                if not cached_metrics:
                    self._last_metrics_result = metrics_result
                if metrics_result.status is not LossRuntimeMetricsReadStatus.AVAILABLE:
                    # If metrics are UNAVAILABLE (specifically) but this is the first dispatch (no prior snapshot),
                    # allow baseline dispatch to proceed with existing runtime state
                    if self._last_snapshot is None and metrics_result.status == LossRuntimeMetricsReadStatus.UNAVAILABLE:
                        # This is a baseline dispatch - use existing runtime state without metrics
                        event_id = f"{request.source}:baseline:{event_type.value}"
                        if reevaluation_token is not None:
                            event_id = f"{event_id}:REEVALUATE:{reevaluation_token.strip()}"
                        # For baseline dispatch, we skip metrics evaluation and event adaptation
                        # Just return IDEMPOTENT to indicate we're using the existing baseline state
                        return _result(
                            LossRuntimeDispatchStatus.IDEMPOTENT,
                            ("baseline dispatch - metrics unavailable",),
                            snapshot=runtime_snapshot,
                        )
                    # For other metrics statuses or subsequent dispatches, return appropriate status
                    target = {
                        LossRuntimeMetricsReadStatus.STALE: LossRuntimeDispatchStatus.STALE,
                        LossRuntimeMetricsReadStatus.FAILED: LossRuntimeDispatchStatus.FAILED,
                        LossRuntimeMetricsReadStatus.PARTIAL: LossRuntimeDispatchStatus.UNAVAILABLE,
                        LossRuntimeMetricsReadStatus.INCONSISTENT: LossRuntimeDispatchStatus.UNAVAILABLE,
                        LossRuntimeMetricsReadStatus.UNAVAILABLE: LossRuntimeDispatchStatus.UNAVAILABLE,
                    }.get(
                        metrics_result.status,
                        LossRuntimeDispatchStatus.UNAVAILABLE,
                    )
                    return _result(
                        target,
                        metrics_result.safe_reasons,
                        snapshot=runtime_snapshot,
                    )
                metrics = metrics_result.metrics
                if cached_metrics and (
                    metrics.captured_at > request.requested_at
                    or request.requested_at - metrics.captured_at
                    > request.maximum_age
                ):
                    return _result(
                        LossRuntimeDispatchStatus.STALE,
                        ("runtime metrics stale",),
                        snapshot=runtime_snapshot,
                    )
                event_id = (
                    f"{request.source}:{metrics.source_revision}:{event_type.value}"
                )
                if reevaluation_token is not None:
                    event_id = f"{event_id}:REEVALUATE:{reevaluation_token}"
                signature = json.dumps(
                    metrics.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                if event_id == self._last_event_id:
                    if signature == self._last_metrics_signature:
                        return _result(
                            LossRuntimeDispatchStatus.IDEMPOTENT,
                            (),
                            event_status=LossRuntimeEventAdapterStatus.IDEMPOTENT.value,
                            snapshot=self._last_snapshot or runtime_snapshot,
                        )
                    return _result(
                        LossRuntimeDispatchStatus.CONFLICT,
                        ("runtime event conflict",),
                        snapshot=runtime_snapshot,
                    )
                if (
                    self._last_snapshot is not None
                    and metrics.captured_at <= self._last_snapshot.updated_at
                    and reevaluation_token is None
                ):
                    return _result(
                        LossRuntimeDispatchStatus.STALE,
                        ("runtime metrics stale",),
                        snapshot=runtime_snapshot,
                    )
                evaluation = self._evaluation_bridge.evaluate(
                    metrics, runtime_snapshot, event_id
                )
                if evaluation.status is LossRuntimeEvaluationStatus.RECOVERY_REQUIRED:
                    return _result(
                        LossRuntimeDispatchStatus.RECOVERY_REQUIRED,
                        evaluation.safe_reasons,
                        snapshot=runtime_snapshot,
                    )
                if evaluation.status is not LossRuntimeEvaluationStatus.SUCCEEDED:
                    return _result(
                        LossRuntimeDispatchStatus.FAILED,
                        evaluation.safe_reasons,
                        snapshot=runtime_snapshot,
                    )
                event = LossRuntimeEvent(
                    event_id,
                    runtime_snapshot.sequence + 1,
                    request.requested_at
                    if reevaluation_token is not None
                    else metrics.captured_at,
                    event_type,
                    metrics.equity,
                    metrics.balance,
                    metrics.available_balance,
                    metrics.realized_pnl,
                    metrics.unrealized_pnl,
                    metrics.daily_pnl,
                    metrics.weekly_pnl,
                    metrics.monthly_pnl,
                    metrics.peak_equity,
                    metrics.drawdown,
                    metrics.open_exposure,
                    metrics.position_count,
                    metrics.trade_count,
                    request.source,
                )
                adapted = self._event_adapter.adapt(
                    event, runtime_snapshot, evaluation.build_context
                )
                if adapted.status is LossRuntimeEventAdapterStatus.FAILED:
                    return _result(
                        _event_failure_status(adapted.failure.code),
                        (adapted.failure.safe_message,),
                        event_status=adapted.status.value,
                        snapshot=runtime_snapshot,
                    )
                self._last_event_id = event_id
                self._last_metrics_signature = signature
                self._last_snapshot = runtime_snapshot
                if adapted.status is LossRuntimeEventAdapterStatus.IDEMPOTENT:
                    return _result(
                        LossRuntimeDispatchStatus.IDEMPOTENT,
                        (),
                        event_status=adapted.status.value,
                        snapshot=runtime_snapshot,
                    )
                latest_status = lifecycle.get_status()
                if (
                    not isinstance(latest_status, LossLimitApplicationStatus)
                    or latest_status.lifecycle_state
                    is not ApplicationLifecycleState.RUNNING
                ):
                    return _result(
                        LossRuntimeDispatchStatus.REJECTED,
                        ("lifecycle stopped before update",),
                        event_status=adapted.status.value,
                        snapshot=runtime_snapshot,
                    )
                lifecycle_result = lifecycle.apply_update(adapted.update_request)
                latest_snapshot = lifecycle.get_snapshot()
                if isinstance(latest_snapshot, LossLimitRuntimeSnapshot):
                    self._last_snapshot = latest_snapshot
                projected = _lifecycle_projection(
                    lifecycle_result,
                    latest_snapshot
                    if isinstance(latest_snapshot, LossLimitRuntimeSnapshot)
                    else runtime_snapshot,
                )
                return LossRuntimeDispatchResult(
                    projected.status,
                    adapted.status.value,
                    projected.lifecycle_status,
                    projected.runtime_revision,
                    projected.runtime_sequence,
                    projected.durability_pending,
                    projected.safe_reasons,
                    projected.applied,
                    projected.new_entry_allowed,
                )
            except Exception:
                return _result(
                    LossRuntimeDispatchStatus.FAILED,
                    ("runtime update dispatch failed",),
                )


def dispatch_money_management_runtime_update(
    app,
    dispatcher,
    request,
    event_type,
):
    """Explicit call point. MM-4I intentionally registers no runtime hook."""

    if not isinstance(dispatcher, LossRuntimeUpdateDispatcher):
        return _result(
            LossRuntimeDispatchStatus.FAILED,
            ("runtime update dispatcher invalid",),
        )
    return dispatcher.dispatch(app, request, event_type)
