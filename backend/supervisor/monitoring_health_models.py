"""Pure Phase 3A scheduler health/read model and deterministic reducer.

The health model is a frozen, secret-free projection.  It contains no raw
evidence, no stack traces and no trading-authority fields.  The reducer derives
health only from explicit caller inputs; it never writes state, notifies, or
creates a task.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import Field, field_validator

from .monitoring_models import Availability, Contract, Count, Freshness, Token, aware
from .monitoring_scheduler_models import (
    CONFIG_VERSION, FeatureFlagSource, MonitoringRun, SchedulerConfig, SchedulerState,
    StateRecoveryStatus,
)
from .monitoring_scheduler_state import SchedulerStateModel
from .monitoring_state_models import RecoveryResult

HEALTH_SCHEMA_VERSION = "scheduler-health-v1"


def _aware_optional(value):
    return None if value is None else aware(value)


class MonitoringHealth(Contract):
    """Read-only scheduler health.  Optional defaults keep the schema extensible."""

    schema_version: Token = HEALTH_SCHEMA_VERSION
    enabled: bool = False
    scheduler_state: SchedulerState = "DISABLED"
    feature_flag_source: FeatureFlagSource = "DEFAULT_OFF"
    started_at: datetime | None = None
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_success_at: datetime | None = None
    next_run_at: datetime | None = None
    current_run_id: Token | None = None
    run_count: Count = 0
    success_count: Count = 0
    failure_count: Count = 0
    timeout_count: Count = 0
    skipped_overlap_count: Count = 0
    last_duration_ms: Count | None = None
    last_result_status: Token | None = None
    last_error_code: Token | None = None
    last_error_summary: Token | None = None
    observation_count: Count = 0
    anomaly_count: Count = 0
    active_anomaly_count: Count = 0
    eligible_notification_count: Count = 0
    state_recovery_status: StateRecoveryStatus = "NOT_ATTEMPTED"
    state_corruption_count: Count = 0
    state_partial_recovery: bool = False
    source_freshness: Freshness | None = None
    source_availability: Availability | None = None
    degraded_reasons: tuple[Token, ...] = Field(default=(), max_length=32)
    updated_at: datetime
    last_run_id: Token | None = None

    _aware_fields = field_validator(
        "started_at", "last_run_started_at", "last_run_completed_at", "last_success_at",
        "next_run_at", "updated_at",
    )(_aware_optional)
    _updated = field_validator("updated_at")(aware)

    @field_validator("degraded_reasons")
    @classmethod
    def _sorted(cls, value):
        if len(value) > 32:
            raise ValueError("too many degraded reasons")
        return tuple(sorted(set(value)))


def _previous(previous, field, default):
    return getattr(previous, field) if previous is not None else default


def _recovery_status(recovery: RecoveryResult | None, fallback: StateRecoveryStatus) -> StateRecoveryStatus:
    if recovery is None:
        return fallback
    if recovery.corruption_count:
        return "CORRUPT"
    if recovery.partial:
        return "PARTIAL"
    return "OK"


def reduce_health(
    *,
    scheduler_state: SchedulerStateModel,
    updated_at: datetime,
    previous: MonitoringHealth | None = None,
    completed_run: MonitoringRun | None = None,
    recovery: RecoveryResult | None = None,
    config: SchedulerConfig | None = None,
    feature_flag=None,
    next_run_at: datetime | None = None,
) -> MonitoringHealth:
    """Deterministic health projection from explicit inputs only."""

    updated_at = aware(updated_at)

    counters = {
        "run_count": _previous(previous, "run_count", 0),
        "success_count": _previous(previous, "success_count", 0),
        "failure_count": _previous(previous, "failure_count", 0),
        "timeout_count": _previous(previous, "timeout_count", 0),
        "skipped_overlap_count": _previous(previous, "skipped_overlap_count", 0),
    }
    last_run_id = _previous(previous, "last_run_id", None)
    last_result_status = _previous(previous, "last_result_status", None)
    last_run_started_at = _previous(previous, "last_run_started_at", None)
    last_run_completed_at = _previous(previous, "last_run_completed_at", None)
    last_success_at = _previous(previous, "last_success_at", None)
    last_duration_ms = _previous(previous, "last_duration_ms", None)
    observation_count = _previous(previous, "observation_count", 0)
    anomaly_count = _previous(previous, "anomaly_count", 0)
    active_anomaly_count = _previous(previous, "active_anomaly_count", 0)
    eligible = _previous(previous, "eligible_notification_count", 0)
    source_freshness = _previous(previous, "source_freshness", None)
    source_availability = _previous(previous, "source_availability", None)
    last_error_code = _previous(previous, "last_error_code", None)
    last_error_summary = _previous(previous, "last_error_summary", None)

    duplicate = completed_run is not None and completed_run.run_id == last_run_id

    if completed_run is not None and not duplicate:
        last_run_id = completed_run.run_id
        last_result_status = completed_run.status
        last_run_completed_at = completed_run.completed_at
        if completed_run.status == "SKIPPED_OVERLAP":
            counters["skipped_overlap_count"] += 1
        else:
            counters["run_count"] += 1
            if completed_run.status == "SUCCESS":
                counters["success_count"] += 1
                last_success_at = completed_run.completed_at
            elif completed_run.status == "TIMED_OUT":
                counters["timeout_count"] += 1
            elif completed_run.status == "FAILED":
                counters["failure_count"] += 1
            last_run_started_at = completed_run.started_at
            last_duration_ms = completed_run.duration_ms
            observation_count = completed_run.observation_count
            anomaly_count = completed_run.anomaly_count
            active_anomaly_count = completed_run.active_anomaly_count
            eligible = completed_run.eligible_notification_count
            source_freshness = completed_run.source_freshness
            source_availability = completed_run.source_availability
            last_error_code = completed_run.error_code
            last_error_summary = completed_run.error_summary

    if scheduler_state.state == "FAILED":
        last_error_code = scheduler_state.failure_code or last_error_code

    state_recovery_status = _recovery_status(
        recovery, _previous(previous, "state_recovery_status", "NOT_ATTEMPTED")
    )
    state_corruption_count = (
        recovery.corruption_count if recovery is not None
        else _previous(previous, "state_corruption_count", 0)
    )
    state_partial_recovery = (
        recovery.partial if recovery is not None
        else _previous(previous, "state_partial_recovery", False)
    )

    degraded = set(scheduler_state.degraded_reasons)
    if completed_run is not None and not duplicate:
        if completed_run.partial_result or completed_run.status in ("PARTIAL", "DEGRADED"):
            degraded.add("RUN_DEGRADED")
    if recovery is not None:
        if recovery.partial:
            degraded.add("RECOVERY_PARTIAL")
        if recovery.corruption_count:
            degraded.add("RECOVERY_CORRUPTION_ISOLATED")
    if source_freshness == "STALE":
        degraded.add("SOURCE_STALE")
    if source_availability in ("UNAVAILABLE", "ERROR"):
        degraded.add("SOURCE_UNAVAILABLE")

    if next_run_at is None and config is not None and scheduler_state.enabled \
            and scheduler_state.state in ("IDLE", "DEGRADED"):
        next_run_at = updated_at + timedelta(seconds=config.interval_seconds)

    source = feature_flag.source if feature_flag is not None else _previous(
        previous, "feature_flag_source", "DEFAULT_OFF"
    )

    return MonitoringHealth(
        enabled=scheduler_state.enabled,
        scheduler_state=scheduler_state.state,
        feature_flag_source=source,
        started_at=scheduler_state.started_at,
        last_run_started_at=last_run_started_at,
        last_run_completed_at=last_run_completed_at,
        last_success_at=last_success_at,
        next_run_at=next_run_at,
        current_run_id=scheduler_state.current_run_id,
        run_count=counters["run_count"],
        success_count=counters["success_count"],
        failure_count=counters["failure_count"],
        timeout_count=counters["timeout_count"],
        skipped_overlap_count=counters["skipped_overlap_count"],
        last_duration_ms=last_duration_ms,
        last_result_status=last_result_status,
        last_error_code=last_error_code,
        last_error_summary=last_error_summary,
        observation_count=observation_count,
        anomaly_count=anomaly_count,
        active_anomaly_count=active_anomaly_count,
        eligible_notification_count=eligible,
        state_recovery_status=state_recovery_status,
        state_corruption_count=state_corruption_count,
        state_partial_recovery=state_partial_recovery,
        source_freshness=source_freshness,
        source_availability=source_availability,
        degraded_reasons=tuple(sorted(degraded)),
        updated_at=updated_at,
        last_run_id=last_run_id,
    )


def disabled_health(
    *,
    updated_at: datetime,
    feature_flag=None,
    previous: MonitoringHealth | None = None,
    config_version: str = CONFIG_VERSION,
) -> MonitoringHealth:
    """Flag-OFF health remains readable as DISABLED without starting anything."""

    from .monitoring_scheduler_state import initial_scheduler_state

    return reduce_health(
        scheduler_state=initial_scheduler_state(config_version=config_version),
        updated_at=updated_at, previous=previous, feature_flag=feature_flag,
    )
