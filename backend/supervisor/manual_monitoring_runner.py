"""Explicit, in-process, manually invoked Supervisor monitoring one-shot runner.

This module composes the existing Phase 1 (deterministic one-shot evaluation),
Phase 2 (restart-safe anomaly state and journal) and Phase 3A (scheduler
configuration/state/health) contracts through one explicit call.  It is dormant
until a caller invokes :meth:`ManualMonitoringRunner.run_once`: importing or
constructing the runner performs no monitoring run, no query, no evaluation, no
persistence and no I/O.

Safety boundaries:

- no API route, scheduler, background task, timer, thread or ``asyncio`` task;
- every dependency (clock, query, evaluator, state service) is injected;
- Production paths, readers and stores are never discovered or written;
- a missing/disabled/invalid feature flag or an invalid request performs no
  query, no evaluation and no persistence;
- persistence happens only through an injected Phase 2 ``MonitoringStateService``
  and only when the request explicitly permits it.

Cross-process safety is NOT provided: this runner offers process-local overlap
control only.  ``CROSS_PROCESS_SAFETY=NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Literal

from pydantic import Field, field_validator, model_validator

from .drift_evaluator import Contradiction
from .monitoring_health_models import MonitoringHealth, reduce_health
from .monitoring_models import (
    Availability, Contract, Count, Freshness, Token, aware,
)
from .monitoring_policy import EvaluationPolicy
from .monitoring_scheduler_models import (
    MAX_OBSERVATIONS, FeatureFlagStatus, MonitoringRun, OverlapResult,
    SchedulerConfig, decide_overlap,
)
from .monitoring_scheduler_state import (
    SchedulerStateModel, SchedulerTransition, initial_scheduler_state,
    transition_state,
)
from .monitoring_state_models import MonitoringCycleResult
from .monitoring_state_service import MonitoringStateService, observe
from .monitoring_state_store import AppendOutcome
from .one_shot_monitor import MonitorResult, one_shot_monitor

REQUEST_SCHEMA_VERSION = "manual-run-request-v1"
QUERY_SCHEMA_VERSION = "manual-run-query-v1"
RESULT_SCHEMA_VERSION = "manual-run-result-v1"

RESULT_SCHEMA_VERSION_TOKEN = RESULT_SCHEMA_VERSION

CallerSource = Literal["OPERATOR", "SYSTEM", "TEST", "MANUAL"]
MonitoringScope = Literal["ALL", "HEALTH", "TRADING", "SELECTION"]
ManualRunStatus = Literal[
    "DISABLED", "INVALID", "SKIPPED_OVERLAP", "UNAVAILABLE",
    "SUCCESS", "PARTIAL", "DEGRADED", "FAILED",
]
PersistenceStatus = Literal[
    "NOT_ATTEMPTED", "PERSISTED", "IDEMPOTENT", "PARTIAL", "REJECTED", "FAILED",
]

# Bounded failure/reason codes reported by the runner.
INVALID_REQUEST = "INVALID_REQUEST"
DISABLED_RESULT = "DISABLED_RESULT"
FLAG_INVALID = "FLAG_INVALID"
FLAG_EXPECTATION_MISMATCH = "FLAG_EXPECTATION_MISMATCH"
OVERLAP_SKIPPED = "OVERLAP_SKIPPED"
QUERY_UNAVAILABLE = "QUERY_UNAVAILABLE"
EVALUATION_FAILED = "EVALUATION_FAILED"
TRANSITION_FAILED = "TRANSITION_FAILED"
PERSISTENCE_UNAUTHORIZED = "PERSISTENCE_UNAUTHORIZED"
PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"
PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"
PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
HEALTH_REDUCTION_FAILED = "HEALTH_REDUCTION_FAILED"
SOURCE_PARTIAL = "SOURCE_PARTIAL"

_MAX_WARNING_CODES = 64


def utc_now() -> datetime:
    """Default clock provider.  Tests inject a fixed clock for determinism."""

    return datetime.now(timezone.utc)


def _sorted_unique(values) -> tuple:
    return tuple(sorted(set(values)))


class MonitoringQueryOutcome(Contract):
    """A bounded read-only observation/query response supplied by the caller.

    The runner never queries a source itself; it consumes this explicit result.
    ``observation_inputs`` are handed unchanged to the Phase 1 evaluator, which
    re-applies its own structural budget and per-key validation.
    """

    schema_version: Token = QUERY_SCHEMA_VERSION
    available: bool = True
    observation_inputs: dict[str, Any] = Field(default_factory=dict)
    contradictions: tuple[Contradiction, ...] = Field(default=(), max_length=32)
    source_freshness: Freshness = "FRESH"
    source_availability: Availability = "AVAILABLE"
    provenance: tuple[Token, ...] = Field(default=(), max_length=64)
    corruption_count: Count = 0
    partial_result: bool = False
    warnings: tuple[Token, ...] = Field(default=(), max_length=_MAX_WARNING_CODES)
    error_code: Token | None = None

    @field_validator("provenance", "warnings")
    @classmethod
    def _ordered(cls, value):
        return _sorted_unique(value)


class MonitoringRunRequest(Contract):
    """A validated, bounded manual one-shot request.  No unbounded filters."""

    schema_version: Token = REQUEST_SCHEMA_VERSION
    request_id: Token
    requested_at: datetime
    caller: CallerSource = "MANUAL"
    correlation_id: Token | None = None
    scope: MonitoringScope = "ALL"
    symbols: tuple[Token, ...] = Field(default=(), max_length=32)
    modes: tuple[Token, ...] = Field(default=(), max_length=4)
    max_observations: int = Field(default=128, strict=True, ge=1, le=MAX_OBSERVATIONS)
    dry_run: bool = True
    persist: bool = False
    expected_flag_enabled: bool | None = None
    policy_version: Token | None = None

    _aware = field_validator("requested_at")(aware)

    @field_validator("symbols", "modes")
    @classmethod
    def _ordered(cls, value):
        return _sorted_unique(value)

    @model_validator(mode="after")
    def _coherent(self):
        if self.persist and self.dry_run:
            raise ValueError("dry_run requests cannot persist")
        return self


class ManualRunResult(Contract):
    """A bounded structured manual-run result.  No secrets or raw trace payloads."""

    schema_version: Token = RESULT_SCHEMA_VERSION_TOKEN
    request_id: Token
    run_id: Token | None = None
    correlation_id: Token | None = None
    started_at: datetime | None = None
    finished_at: datetime
    status: ManualRunStatus
    mode: Literal["MANUAL"] = "MANUAL"
    caller: CallerSource | None = None
    feature_flag: FeatureFlagStatus
    overlap: OverlapResult | None = None
    evaluation: MonitorResult | None = None
    cycle: MonitoringCycleResult | None = None
    health: MonitoringHealth | None = None
    observation_count: Count = 0
    evaluation_count: Count = 0
    anomaly_count: Count = 0
    active_anomaly_count: Count = 0
    eligible_notification_count: Count = 0
    state_event_count: Count = 0
    persisted_event_count: Count = 0
    persistence_status: PersistenceStatus = "NOT_ATTEMPTED"
    provenance: tuple[Token, ...] = Field(default=(), max_length=64)
    source_freshness: Freshness | None = None
    source_availability: Availability | None = None
    partial_result: bool = False
    corruption_count: Count = 0
    warnings: tuple[Token, ...] = Field(default=(), max_length=_MAX_WARNING_CODES)
    errors: tuple[Token, ...] = Field(default=(), max_length=_MAX_WARNING_CODES)

    _aware = field_validator("started_at", "finished_at")(lambda v: None if v is None else aware(v))

    @field_validator("provenance", "warnings", "errors")
    @classmethod
    def _ordered(cls, value):
        return _sorted_unique(value)


def _derive_run_id(request: MonitoringRunRequest) -> str:
    payload = f"{request.request_id}:{request.requested_at.isoformat()}"
    return sha256(payload.encode("utf-8")).hexdigest()[:32]


def _is_anomaly(result) -> bool:
    return result.severity in ("WARNING", "CRITICAL") or result.state == "CRITICAL"


class ManualMonitoringRunner:
    """Dormant, explicit manual one-shot runner over injected dependencies.

    Construction performs no work.  Only :meth:`run_once` executes a bounded,
    process-local, observation-only pipeline.
    """

    def __init__(
        self,
        *,
        query: Callable[[MonitoringRunRequest], MonitoringQueryOutcome],
        config: SchedulerConfig | None = None,
        policy: EvaluationPolicy | None = None,
        evaluator: Callable[..., MonitorResult] = one_shot_monitor,
        state_service: MonitoringStateService | None = None,
        feature_flag: FeatureFlagStatus | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(query):
            raise TypeError("an explicit callable query dependency is required")
        if not callable(evaluator):
            raise TypeError("an explicit callable evaluator dependency is required")
        if state_service is not None and not isinstance(state_service, MonitoringStateService):
            raise TypeError("state_service must be a MonitoringStateService or None")
        self._query = query
        self._config = config if config is not None else SchedulerConfig()
        self._policy = policy if policy is not None else EvaluationPolicy()
        self._evaluator = evaluator
        self._state_service = state_service
        self._feature_flag = feature_flag if feature_flag is not None else FeatureFlagStatus()
        self._clock = clock if clock is not None else utc_now
        self._active_run_id: str | None = None
        self._active_request_id: str | None = None

    # -- read-only introspection ------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._active_run_id is not None

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    # -- result builders ---------------------------------------------------

    def _result(self, request_id, finished_at, status, **fields) -> ManualRunResult:
        return ManualRunResult(
            request_id=request_id, finished_at=finished_at, status=status,
            feature_flag=self._feature_flag, **fields,
        )

    # -- scheduler state ---------------------------------------------------

    @staticmethod
    def _running_state(started_at: datetime, run_id: str) -> SchedulerStateModel:
        state = initial_scheduler_state(at=started_at)
        state = transition_state(
            state, SchedulerTransition(event="ENABLE_REQUESTED", requested_at=started_at)
        ).state
        state = transition_state(
            state, SchedulerTransition(event="STARTUP_COMPLETE", requested_at=started_at)
        ).state
        return transition_state(
            state,
            SchedulerTransition(
                event="RUN_START", requested_at=started_at, run_id=run_id,
                trigger_type="MANUAL",
            ),
        ).state

    @staticmethod
    def _final_state(state, finished_at, outcome: str, failure_code: str) -> SchedulerStateModel:
        if outcome == "SUCCESS":
            return transition_state(
                state, SchedulerTransition(event="RUN_SUCCESS", requested_at=finished_at)
            ).state
        if outcome == "DEGRADED":
            return transition_state(
                state, SchedulerTransition(event="RUN_PARTIAL", requested_at=finished_at)
            ).state
        return transition_state(
            state,
            SchedulerTransition(
                event="RUN_FAILURE", requested_at=finished_at,
                failure_code=failure_code, escalate_failure=True,
            ),
        ).state

    # -- pipeline ----------------------------------------------------------

    def run_once(self, request: MonitoringRunRequest | dict) -> ManualRunResult:
        """Execute exactly one bounded manual run, or return a structured refusal."""

        try:
            if not isinstance(request, MonitoringRunRequest):
                request = MonitoringRunRequest.model_validate(request)
        except Exception:
            finished_at = aware(self._clock())
            return self._result(
                "UNKNOWN", finished_at, "INVALID", errors=(INVALID_REQUEST,),
            )

        flag = self._feature_flag
        if not flag.valid:
            return self._result(
                request.request_id, aware(self._clock()), "DISABLED",
                caller=request.caller, correlation_id=request.correlation_id,
                errors=(FLAG_INVALID,),
            )
        if not flag.enabled:
            return self._result(
                request.request_id, aware(self._clock()), "DISABLED",
                caller=request.caller, correlation_id=request.correlation_id,
                errors=(DISABLED_RESULT,),
            )
        if request.expected_flag_enabled is not None and \
                request.expected_flag_enabled != flag.enabled:
            return self._result(
                request.request_id, aware(self._clock()), "INVALID",
                caller=request.caller, correlation_id=request.correlation_id,
                errors=(FLAG_EXPECTATION_MISMATCH,),
            )
        if request.max_observations > self._config.max_observations:
            return self._result(
                request.request_id, aware(self._clock()), "INVALID",
                caller=request.caller, correlation_id=request.correlation_id,
                errors=(INVALID_REQUEST,),
            )
        if request.persist and self._state_service is None:
            return self._result(
                request.request_id, aware(self._clock()), "INVALID",
                caller=request.caller, correlation_id=request.correlation_id,
                errors=(PERSISTENCE_UNAUTHORIZED,),
            )

        overlap = decide_overlap(
            scheduler_state="RUNNING" if self.is_running else "IDLE",
            trigger_type="MANUAL",
            request_id=request.request_id,
            active_run_id=self._active_run_id,
        )
        if overlap.decision in ("REJECT_OVERLAP", "REPLAY_EXISTING"):
            return self._result(
                request.request_id, aware(self._clock()), "SKIPPED_OVERLAP",
                caller=request.caller, correlation_id=request.correlation_id,
                overlap=overlap, errors=(OVERLAP_SKIPPED,),
            )

        run_id = _derive_run_id(request)
        self._active_run_id = run_id
        self._active_request_id = request.request_id
        started_at = aware(self._clock())
        try:
            return self._execute(request, run_id, started_at)
        finally:
            self._active_run_id = None
            self._active_request_id = None

    def _execute(self, request, run_id, started_at) -> ManualRunResult:
        warnings: set[str] = set()
        errors: set[str] = set()
        state = self._running_state(started_at, run_id)

        outcome, query_error = self._read_observation(request)
        finished_at = aware(self._clock())

        if query_error is not None or not outcome.available:
            errors.add(outcome.error_code if outcome and outcome.error_code else QUERY_UNAVAILABLE)
            final = self._final_state(state, finished_at, "FAILED", QUERY_UNAVAILABLE)
            return self._finish(
                request, run_id, started_at, finished_at, state, final,
                status="UNAVAILABLE", warnings=warnings, errors=errors,
                source_freshness=(outcome.source_freshness if outcome else "UNKNOWN"),
                source_availability=(outcome.source_availability if outcome else "UNAVAILABLE"),
                partial_result=True, error_code=QUERY_UNAVAILABLE,
                outcome=None, evaluation=None, cycle=None, persisted=0,
                persistence_status="NOT_ATTEMPTED", recovery=None,
            )

        warnings.update(outcome.warnings)
        if outcome.partial_result:
            warnings.add(SOURCE_PARTIAL)

        evaluation, evaluator_error = self._evaluate(request, outcome, started_at)
        if evaluator_error is not None:
            errors.add(EVALUATION_FAILED)
            final = self._final_state(state, finished_at, "FAILED", EVALUATION_FAILED)
            return self._finish(
                request, run_id, started_at, finished_at, state, final,
                status="FAILED", warnings=warnings, errors=errors,
                source_freshness=outcome.source_freshness,
                source_availability=outcome.source_availability,
                partial_result=True, corruption_count=outcome.corruption_count,
                outcome=outcome, evaluation=None, cycle=None, persisted=0,
                persistence_status="NOT_ATTEMPTED", recovery=None,
            )

        if evaluation.partial_result:
            warnings.add("INCOMPLETE_EVALUATION")

        observations = tuple(observe(result) for result in evaluation.results)
        cycle, transition_error = self._transition(observations, started_at)
        if transition_error is not None:
            errors.add(TRANSITION_FAILED)
            final = self._final_state(state, finished_at, "FAILED", TRANSITION_FAILED)
            return self._finish(
                request, run_id, started_at, finished_at, state, final,
                status="FAILED", warnings=warnings, errors=errors,
                source_freshness=outcome.source_freshness,
                source_availability=outcome.source_availability,
                partial_result=True, corruption_count=outcome.corruption_count,
                outcome=outcome, evaluation=evaluation, cycle=None, persisted=0,
                persistence_status="NOT_ATTEMPTED", recovery=None,
            )

        persisted, persistence_status, persistence_warnings, persistence_errors = \
            self._persist(request, cycle)
        warnings.update(persistence_warnings)
        errors.update(persistence_errors)

        if evaluation.partial_result or outcome.partial_result:
            run_status = "PARTIAL"
        elif persistence_status == "REJECTED" or persistence_errors:
            run_status = "DEGRADED"
        else:
            run_status = "SUCCESS"
        final = self._final_state(
            state, finished_at,
            "DEGRADED" if run_status in ("PARTIAL", "DEGRADED") else "SUCCESS",
            PERSISTENCE_REJECTED if run_status == "DEGRADED" else "",
        )
        return self._finish(
            request, run_id, started_at, finished_at, state, final,
            status=run_status, warnings=warnings, errors=errors,
            source_freshness=outcome.source_freshness,
            source_availability=outcome.source_availability,
            partial_result=evaluation.partial_result or outcome.partial_result,
            corruption_count=outcome.corruption_count
            + (cycle.recovery.corruption_count if cycle and cycle.recovery else 0),
            outcome=outcome, evaluation=evaluation, cycle=cycle,
            persisted=persisted, persistence_status=persistence_status,
            recovery=cycle.recovery if cycle else None,
        )

    # -- stages ------------------------------------------------------------

    def _read_observation(self, request):
        try:
            outcome = self._query(request)
            if isinstance(outcome, dict):
                outcome = MonitoringQueryOutcome.model_validate(outcome)
            elif not isinstance(outcome, MonitoringQueryOutcome):
                raise TypeError("query must return MonitoringQueryOutcome")
            return outcome, None
        except Exception:
            return None, "QUERY_UNAVAILABLE"

    def _evaluate(self, request, outcome, evaluated_at):
        try:
            evaluation = self._evaluator(
                outcome.observation_inputs, policy=self._policy,
                evaluated_at=evaluated_at, contradictions=outcome.contradictions,
            )
            if not isinstance(evaluation, MonitorResult):
                raise TypeError("evaluator must return MonitorResult")
            return evaluation, None
        except Exception:
            return None, "EVALUATION_FAILED"

    def _transition(self, observations, evaluated_at):
        if self._state_service is None:
            return None, None
        try:
            return self._state_service.reduce(observations, evaluated_at=evaluated_at), None
        except Exception:
            return None, "TRANSITION_FAILED"

    def _persist(self, request, cycle):
        if not request.persist or cycle is None or not cycle.events:
            return 0, "NOT_ATTEMPTED", set(), set()
        if self._state_service is None:
            return 0, "REJECTED", set(), {PERSISTENCE_UNAUTHORIZED}
        try:
            outcomes = tuple(self._state_service.persist(cycle))
        except Exception:
            return 0, "FAILED", {PERSISTENCE_FAILED}, {PERSISTENCE_FAILED}
        written = sum(1 for o in outcomes if o.outcome is AppendOutcome.WRITTEN)
        warnings: set[str] = set()
        errors: set[str] = set()
        if any(o.outcome is AppendOutcome.REJECTED for o in outcomes):
            warnings.add(PERSISTENCE_REJECTED)
            return written, "REJECTED", warnings, errors
        if any(o.outcome is AppendOutcome.CONFLICT for o in outcomes):
            warnings.add(PERSISTENCE_CONFLICT)
            return written, "PARTIAL", warnings, errors
        if written:
            return written, "PERSISTED", warnings, errors
        return 0, "IDEMPOTENT", warnings, errors

    def _finish(self, request, run_id, started_at, finished_at, state, final_state,
                *, status, warnings, errors, source_freshness, source_availability,
                partial_result, outcome, evaluation, cycle, persisted,
                persistence_status, recovery, error_code=None, corruption_count=0):
        observation_count = evaluation.result_count if evaluation else 0
        evaluation_count = evaluation.evaluated_count if evaluation else 0
        anomaly_count = (
            sum(1 for r in evaluation.results if _is_anomaly(r)) if evaluation else 0
        )
        active_anomaly_count = (
            sum(1 for s in cycle.states if s.active and s.current_severity != "NONE")
            if cycle else 0
        )
        eligible = len(cycle.eligible_for_notification) if cycle else 0
        state_event_count = len(cycle.events) if cycle else 0
        provenance = outcome.provenance if outcome else ()

        monitoring_run = None
        if status != "SKIPPED_OVERLAP":
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            run_status = {
                "SUCCESS": "SUCCESS", "PARTIAL": "PARTIAL", "DEGRADED": "DEGRADED",
            }.get(status, "FAILED")
            resolved_error = error_code
            if resolved_error is None and errors:
                resolved_error = sorted(errors)[0]
            monitoring_run = MonitoringRun(
                run_id=run_id, trigger_type="MANUAL", requested_at=request.requested_at,
                started_at=started_at, completed_at=finished_at, status=run_status,
                timeout_seconds=self._config.run_timeout_seconds, duration_ms=duration_ms,
                observation_count=observation_count, evaluation_count=evaluation_count,
                anomaly_count=anomaly_count, active_anomaly_count=active_anomaly_count,
                eligible_notification_count=eligible, state_event_count=state_event_count,
                source_freshness=source_freshness, source_availability=source_availability,
                partial_result=partial_result, error_code=resolved_error,
            )

        health = None
        try:
            health = reduce_health(
                scheduler_state=final_state, updated_at=finished_at,
                completed_run=monitoring_run, recovery=recovery,
                config=self._config, feature_flag=self._feature_flag,
            )
        except Exception:
            warnings = set(warnings) | {HEALTH_REDUCTION_FAILED}

        return self._result(
            request.request_id, finished_at, status,
            run_id=run_id, correlation_id=request.correlation_id,
            started_at=started_at, caller=request.caller,
            evaluation=evaluation, cycle=cycle, health=health,
            observation_count=observation_count, evaluation_count=evaluation_count,
            anomaly_count=anomaly_count, active_anomaly_count=active_anomaly_count,
            eligible_notification_count=eligible, state_event_count=state_event_count,
            persisted_event_count=persisted, persistence_status=persistence_status,
            provenance=provenance, source_freshness=source_freshness,
            source_availability=source_availability, partial_result=partial_result,
            corruption_count=corruption_count, warnings=tuple(warnings),
            errors=tuple(errors),
        )
