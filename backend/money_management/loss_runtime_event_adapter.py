"""MM-4H side-effect-free runtime event adapter and request builder."""
import json
from threading import RLock

from .loss_runtime_event_models import (
    LossRuntimeEvent,
    LossRuntimeEventAdapterResult,
    LossRuntimeEventAdapterStatus,
    LossRuntimeEventFailure,
    LossRuntimeEventFailureCode,
    LossRuntimeEventSnapshotProjection,
    LossRuntimeUpdateBuildContext,
)
from .loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
    LossLimitRuntimeUpdate,
)


def project_loss_runtime_event(event):
    if not isinstance(event, LossRuntimeEvent):
        raise TypeError("runtime event required")
    return LossRuntimeEventSnapshotProjection(
        event.sequence,
        event.occurred_at,
        event.event_type,
        event.equity,
        event.realized_pnl,
        event.unrealized_pnl,
        event.daily_pnl,
        event.weekly_pnl,
        event.monthly_pnl,
        event.peak_equity,
        event.drawdown,
        event.open_exposure,
        event.position_count,
        event.trade_count,
        event.source,
    )


def build_loss_runtime_update_request(event, runtime_snapshot, build_context):
    if not isinstance(event, LossRuntimeEvent):
        raise TypeError("runtime event required")
    if not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot):
        raise TypeError("runtime snapshot required")
    if not isinstance(build_context, LossRuntimeUpdateBuildContext):
        raise TypeError("update build context required")
    if build_context.event_id != event.event_id:
        raise ValueError("event context mismatch")
    if event.sequence != runtime_snapshot.sequence + 1:
        raise ValueError("event sequence does not follow runtime snapshot")
    if event.occurred_at <= runtime_snapshot.updated_at:
        raise ValueError("event timestamp does not follow runtime snapshot")
    return LossLimitRuntimeUpdate(
        build_context.next_state,
        build_context.governance_projection,
        build_context.recovery_requirement,
        build_context.save_triggers,
        runtime_snapshot.revision,
        event.sequence,
        event.occurred_at,
        build_context.transition_reason,
    )


def _failure(code, message):
    return LossRuntimeEventAdapterResult(
        LossRuntimeEventAdapterStatus.FAILED,
        None,
        None,
        False,
        LossRuntimeEventFailure(code, message),
    )


def _signature(event, context):
    return json.dumps(
        {"event": event.to_dict(), "context": context.to_dict()},
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


class LossRuntimeEventAdapter:
    """Orders events for one runtime stream and builds update requests only."""

    def __init__(self):
        self._lock = RLock()
        self._last_event_key = None
        self._last_signature = None
        self._last_request = None
        self._last_projection = None
        self._last_sequence = None
        self._last_occurred_at = None

    def adapt(self, event, runtime_snapshot, build_context):
        if not isinstance(event, LossRuntimeEvent):
            return _failure(
                LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_INVALID,
                "runtime event invalid",
            )
        if not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot) or not isinstance(
            build_context, LossRuntimeUpdateBuildContext
        ):
            return _failure(
                LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_CONTEXT_INVALID,
                "runtime event context invalid",
            )
        with self._lock:
            try:
                key = (event.sequence, event.occurred_at, event.event_id)
                signature = _signature(event, build_context)
                if key == self._last_event_key:
                    if signature == self._last_signature:
                        return LossRuntimeEventAdapterResult(
                            LossRuntimeEventAdapterStatus.IDEMPOTENT,
                            self._last_request,
                            self._last_projection,
                            True,
                            None,
                        )
                    return _failure(
                        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_CONFLICT,
                        "runtime event conflict",
                    )
                if (
                    self._last_sequence is not None
                    and event.sequence <= self._last_sequence
                ):
                    return _failure(
                        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_STALE,
                        "runtime event is stale",
                    )
                expected_sequence = runtime_snapshot.sequence + 1
                if event.sequence < expected_sequence:
                    return _failure(
                        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_STALE,
                        "runtime event is stale",
                    )
                if event.sequence > expected_sequence:
                    return _failure(
                        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_SEQUENCE_GAP,
                        "runtime event sequence gap",
                    )
                if (
                    event.occurred_at <= runtime_snapshot.updated_at
                    or (
                        self._last_occurred_at is not None
                        and event.occurred_at <= self._last_occurred_at
                    )
                ):
                    return _failure(
                        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_TIMESTAMP_INVALID,
                        "runtime event timestamp invalid",
                    )
                try:
                    request = build_loss_runtime_update_request(
                        event, runtime_snapshot, build_context
                    )
                    projection = project_loss_runtime_event(event)
                except (TypeError, ValueError):
                    return _failure(
                        LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_CONTEXT_INVALID,
                        "runtime event context invalid",
                    )
                self._last_event_key = key
                self._last_signature = signature
                self._last_request = request
                self._last_projection = projection
                self._last_sequence = event.sequence
                self._last_occurred_at = event.occurred_at
                return LossRuntimeEventAdapterResult(
                    LossRuntimeEventAdapterStatus.SUCCEEDED,
                    request,
                    projection,
                    True,
                    None,
                )
            except Exception:
                return _failure(
                    LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_INTERNAL_FAILURE,
                    "runtime event adaptation failed",
                )
