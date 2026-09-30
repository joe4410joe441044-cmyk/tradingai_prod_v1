"""Read-only Supervisor monitoring health/state projection.

This module builds a bounded, sanitized read model from **injected** monitoring
dependencies.  It never starts a run, never constructs or invokes
``ManualMonitoringRunner``, never schedules work, never reads the Production
trading trace and never writes anything.  Importing or constructing the service
performs no I/O.

The preferred input is an already-recovered Phase 2 ``RecoveryResult`` so that a
request does not touch the disk.  A read-only Phase 2 ``MonitoringStateStore`` may
be supplied instead; only its bounded ``recover()`` is used, and the journal is
never created, repaired, truncated, compacted or rewritten.

When a dependency is not configured the service returns an explicit
``UNAVAILABLE``/``NOT_CONFIGURED``/``DISABLED`` status.  Missing data is never
reported as healthy or as a zero-anomaly success.

Cross-process safety is NOT provided:
``CROSS_PROCESS_SAFETY=NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal

from pydantic import Field, field_validator

from .monitoring_health_models import MonitoringHealth, reduce_health
from .monitoring_models import Availability, Contract, Count, Freshness, Token, aware
from .monitoring_scheduler_models import (
    FeatureFlagStatus, SchedulerConfig, SchedulerState, StateRecoveryStatus,
)
from .monitoring_scheduler_state import SchedulerStateModel
from .monitoring_state_models import RecoveryResult
from .monitoring_state_store import MonitoringStateStore
from .supervisor_control_plane import ControlPlaneStatus

HEALTH_READ_SCHEMA_VERSION = "supervisor-monitoring-read-v1"

FEATURE_FLAG_NAME = "AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED"
CROSS_PROCESS_SAFETY = "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED"

ReadStatus = Literal[
    "AVAILABLE", "PARTIAL", "UNAVAILABLE", "NOT_CONFIGURED", "DISABLED", "STALE", "CORRUPT",
]
ActivationStatus = Literal[
    "DISABLED", "INVALID", "CONFIGURED_ENABLED_INACTIVE", "NOT_CONFIGURED",
]

JOURNAL_MISSING = "JOURNAL_MISSING"
JOURNAL_PARTIAL = "JOURNAL_PARTIAL"
JOURNAL_CORRUPT = "JOURNAL_CORRUPT"
JOURNAL_READ_FAILED = "JOURNAL_READ_FAILED"
HEALTH_REDUCTION_FAILED = "HEALTH_REDUCTION_FAILED"
LAST_RUN_UNAVAILABLE = "LAST_RUN_UNAVAILABLE"
CONTROL_PLANE_UNAVAILABLE = "CONTROL_PLANE_UNAVAILABLE"

_MAX_CODES = 64


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sorted_unique(values) -> tuple:
    return tuple(sorted(set(values)))


class AnomalyCounts(Contract):
    """Bounded lifecycle counts derived only from recovered state."""

    totalCount: Count = 0
    activeCount: Count = 0
    acknowledgedCount: Count = 0
    resolvedCount: Count = 0
    suppressedCount: Count = 0
    unknownCount: Count = 0
    cooldownCount: Count = 0


class ManualRunSummary(Contract):
    """Bounded projection of a Phase 3B manual run result (no raw evidence)."""

    runId: Token
    mode: Token
    status: Token
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    persistenceStatus: Token = "NOT_ATTEMPTED"
    persistedEventCount: Count = 0
    partialResult: bool = False
    anomalyCount: Count = 0
    observationCount: Count = 0
    warnings: tuple[Token, ...] = Field(default=(), max_length=_MAX_CODES)
    errors: tuple[Token, ...] = Field(default=(), max_length=_MAX_CODES)
    provenance: tuple[Token, ...] = Field(default=(), max_length=_MAX_CODES)
    sourceFreshness: Freshness | None = None
    sourceAvailability: Availability | None = None

    _aware = field_validator("startedAt", "finishedAt")(
        lambda v: None if v is None else aware(v)
    )

    @field_validator("warnings", "errors", "provenance")
    @classmethod
    def _ordered(cls, value):
        return _sorted_unique(value)

    @classmethod
    def from_run(cls, run) -> "ManualRunSummary":
        """Duck-typed projection; the runner module is never imported."""

        return cls(
            runId=run.run_id, mode=run.mode, status=run.status,
            startedAt=run.started_at, finishedAt=run.finished_at,
            persistenceStatus=run.persistence_status,
            persistedEventCount=run.persisted_event_count,
            partialResult=run.partial_result, anomalyCount=run.anomaly_count,
            observationCount=run.observation_count, warnings=run.warnings,
            errors=run.errors, provenance=run.provenance,
            sourceFreshness=run.source_freshness,
            sourceAvailability=run.source_availability,
        )


class MonitoringReadResponse(Contract):
    """Bounded read-only monitoring response.  No secrets, paths or raw traces."""

    schemaVersion: Token = HEALTH_READ_SCHEMA_VERSION
    generatedAt: datetime
    observedAt: datetime | None = None
    featureFlagName: Token = FEATURE_FLAG_NAME
    featureEnabled: bool = False
    defaultEnabled: bool = False
    activationStatus: ActivationStatus = "NOT_CONFIGURED"
    schedulerState: SchedulerState | None = None
    schedulerConnected: bool = False
    backgroundTaskActive: bool = False
    lastRunId: Token | None = None
    lastRunMode: Token | None = None
    lastRunStatus: Token | None = None
    lastStartedAt: datetime | None = None
    lastFinishedAt: datetime | None = None
    lastRun: ManualRunSummary | None = None
    anomalyCounts: AnomalyCounts = Field(default_factory=AnomalyCounts)
    totalCount: Count = 0
    activeCount: Count = 0
    acknowledgedCount: Count = 0
    resolvedCount: Count = 0
    suppressedCount: Count = 0
    cooldownCount: Count = 0
    journalAvailability: ReadStatus = "NOT_CONFIGURED"
    recoveryStatus: StateRecoveryStatus = "NOT_ATTEMPTED"
    recordsRead: Count = 0
    bytesRead: Count = 0
    corruptionCount: Count = 0
    partialResult: bool = False
    freshness: Freshness = "UNKNOWN"
    provenance: tuple[Token, ...] = Field(default=(), max_length=_MAX_CODES)
    availability: ReadStatus = "NOT_CONFIGURED"
    warnings: tuple[Token, ...] = Field(default=(), max_length=_MAX_CODES)
    health: MonitoringHealth | None = None
    controlPlane: ControlPlaneStatus | None = None
    crossProcessSafety: Token = CROSS_PROCESS_SAFETY
    productionActivationAllowed: bool = False

    _aware = field_validator(
        "generatedAt", "observedAt", "lastStartedAt", "lastFinishedAt"
    )(lambda v: None if v is None else aware(v))

    @field_validator("provenance", "warnings")
    @classmethod
    def _ordered(cls, value):
        return _sorted_unique(value)


class MonitoringReadService:
    """Read-only projection over injected monitoring dependencies.

    All dependencies are optional.  Nothing is discovered implicitly and no
    Production service or path is resolved.
    """

    def __init__(
        self,
        *,
        feature_flag: FeatureFlagStatus | None = None,
        store: MonitoringStateStore | None = None,
        recovery: RecoveryResult | None = None,
        scheduler_state: SchedulerStateModel | None = None,
        health: MonitoringHealth | None = None,
        last_run=None,
        config: SchedulerConfig | None = None,
        freshness: Freshness | None = None,
        provenance: tuple[Token, ...] = (),
        warnings: tuple[Token, ...] = (),
        clock: Callable[[], datetime] | None = None,
        control_plane=None,
    ) -> None:
        if store is not None and not isinstance(store, MonitoringStateStore):
            raise TypeError("store must be a MonitoringStateStore or None")
        if recovery is not None and not isinstance(recovery, RecoveryResult):
            raise TypeError("recovery must be a RecoveryResult or None")
        if scheduler_state is not None and not isinstance(scheduler_state, SchedulerStateModel):
            raise TypeError("scheduler_state must be a SchedulerStateModel or None")
        self._feature_flag = feature_flag
        self._store = store
        self._recovery = recovery
        self._scheduler_state = scheduler_state
        self._health = health
        self._last_run = last_run
        self._config = config if config is not None else SchedulerConfig()
        self._freshness = freshness
        self._provenance = tuple(provenance)
        self._warnings = tuple(warnings)
        self._clock = clock if clock is not None else _now
        self._control_plane = control_plane

    def read(self) -> MonitoringReadResponse:
        """Build the bounded read model.  Never executes a monitoring run."""

        generated_at = aware(self._clock())
        warnings: set[str] = set(self._warnings)

        flag = self._feature_flag if self._feature_flag is not None else FeatureFlagStatus()
        feature_enabled = bool(flag.enabled and flag.valid)
        if not flag.valid:
            activation_status: ActivationStatus = "INVALID"
        elif not flag.enabled:
            activation_status = "DISABLED"
        else:
            activation_status = "CONFIGURED_ENABLED_INACTIVE"

        recovery, read_failed = self._recovery_snapshot(warnings)

        if recovery is None:
            journal_availability: ReadStatus = "UNAVAILABLE" if read_failed else "NOT_CONFIGURED"
            recovery_status: StateRecoveryStatus = "UNAVAILABLE" if read_failed else "NOT_ATTEMPTED"
            records_read = bytes_read = corruption_count = 0
            partial_result = False
            states: tuple = ()
        elif not recovery.exists:
            warnings.add(JOURNAL_MISSING)
            journal_availability = "UNAVAILABLE"
            recovery_status = "UNAVAILABLE"
            records_read = recovery.records_read
            bytes_read = recovery.bytes_read
            corruption_count = recovery.corruption_count
            partial_result = recovery.partial
            states = ()
        else:
            warnings.update(recovery.warnings)
            records_read = recovery.records_read
            bytes_read = recovery.bytes_read
            corruption_count = recovery.corruption_count
            partial_result = recovery.partial
            states = recovery.states
            if recovery.corruption_count:
                journal_availability = "CORRUPT"
                recovery_status = "CORRUPT"
                warnings.add(JOURNAL_CORRUPT)
            elif recovery.partial:
                journal_availability = "PARTIAL"
                recovery_status = "PARTIAL"
                warnings.add(JOURNAL_PARTIAL)
            else:
                journal_availability = "AVAILABLE"
                recovery_status = "OK"

        counts = _counts(states)

        health, scheduler_state = self._health_snapshot(flag, generated_at, warnings)

        last_run_summary = None
        last_run_fields: dict = {}
        if self._last_run is not None:
            try:
                last_run_summary = ManualRunSummary.from_run(self._last_run)
                last_run_fields = {
                    "lastRunId": last_run_summary.runId,
                    "lastRunMode": last_run_summary.mode,
                    "lastRunStatus": last_run_summary.status,
                    "lastStartedAt": last_run_summary.startedAt,
                    "lastFinishedAt": last_run_summary.finishedAt,
                }
            except Exception:
                warnings.add(LAST_RUN_UNAVAILABLE)

        if self._provenance:
            provenance = self._provenance
        elif states:
            provenance = ("SUPERVISOR_MONITORING_JOURNAL",)
        else:
            provenance = ()

        control_plane_status = None
        if self._control_plane is not None:
            try:
                control_plane_status = self._control_plane.status()
            except Exception:  # noqa: BLE001 - control-plane status is best effort
                warnings.add(CONTROL_PLANE_UNAVAILABLE)
                control_plane_status = None

        return MonitoringReadResponse(
            generatedAt=generated_at,
            observedAt=generated_at if states else None,
            featureEnabled=feature_enabled,
            defaultEnabled=False,
            activationStatus=activation_status,
            schedulerState=scheduler_state,
            schedulerConnected=False,
            backgroundTaskActive=False,
            lastRun=last_run_summary,
            anomalyCounts=counts,
            totalCount=counts.totalCount,
            activeCount=counts.activeCount,
            acknowledgedCount=counts.acknowledgedCount,
            resolvedCount=counts.resolvedCount,
            suppressedCount=counts.suppressedCount,
            cooldownCount=counts.cooldownCount,
            journalAvailability=journal_availability,
            recoveryStatus=recovery_status,
            recordsRead=records_read,
            bytesRead=bytes_read,
            corruptionCount=corruption_count,
            partialResult=partial_result,
            freshness=self._freshness if self._freshness is not None else "UNKNOWN",
            provenance=provenance,
            availability=journal_availability,
            warnings=tuple(warnings),
            health=health,
            controlPlane=control_plane_status,
            crossProcessSafety=CROSS_PROCESS_SAFETY,
            productionActivationAllowed=False,
            **last_run_fields,
        )

    # -- internals ---------------------------------------------------------

    def _recovery_snapshot(self, warnings: set[str]):
        if self._recovery is not None:
            return self._recovery, False
        if self._store is None:
            return None, False
        try:
            return self._store.recover(), False
        except Exception:
            warnings.add(JOURNAL_READ_FAILED)
            return None, True

    def _health_snapshot(self, flag, generated_at, warnings: set[str]):
        model = self._scheduler_state
        if self._health is not None:
            state = model.state if model is not None else self._health.scheduler_state
            return self._health, state
        if model is None:
            return None, None
        try:
            health = reduce_health(
                scheduler_state=model, updated_at=generated_at,
                config=self._config, feature_flag=flag,
            )
            return health, model.state
        except Exception:
            warnings.add(HEALTH_REDUCTION_FAILED)
            return None, model.state


def _counts(states) -> AnomalyCounts:
    return AnomalyCounts(
        totalCount=len(states),
        activeCount=sum(1 for s in states if s.active and s.lifecycle_state != "RESOLVED"),
        acknowledgedCount=sum(1 for s in states if s.lifecycle_state == "ACKNOWLEDGED"),
        resolvedCount=sum(1 for s in states if s.lifecycle_state == "RESOLVED"),
        suppressedCount=sum(1 for s in states if s.lifecycle_state == "SUPPRESSED"),
        unknownCount=sum(1 for s in states if s.lifecycle_state == "UNKNOWN"),
        cooldownCount=sum(1 for s in states if s.active and s.cooldown_until is not None),
    )
