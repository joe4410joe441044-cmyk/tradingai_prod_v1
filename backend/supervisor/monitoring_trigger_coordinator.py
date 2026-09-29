"""Fenced cross-process trigger coordinator (Work I③, Phase 3D-2C).

This module is the last in-process execution-infrastructure layer before a
future authenticated Supervisor manual-trigger route (Phase 3D-3, separately
approved and still blocked).  It composes the existing authorities rather than
reimplementing them:

* the Phase 3D-1 bounded trigger request, authorization and feature-flag models;
* the Phase 3D-2A durable SQLite idempotency authority (duck-typed, injected);
* the Phase 3D-2B OS advisory ownership lock and generation fencing;
* a caller-injected runner callable; and
* bounded, sanitized coordinator result and audit models.

It deliberately does **not** add or register an API route, does not import a web
framework, does not import or invoke the Production one-shot monitoring runner, does not read
Production traces, does not execute monitoring, does not persist anomaly state,
does not schedule work, does not deliver alerts and does not grant any trading
authority.  The runner is an injected callable; the module has no Production
composition and requires explicit caller-supplied dependencies and paths.

Authority boundary (neither authority silently replaces the other):

* SQLite idempotency remains authoritative for claim ownership, the request
  fingerprint, terminal response replay, stale-writer rejection, restart
  recovery and bounded retention;
* the OS advisory lock remains authoritative only for the current cross-process
  execution ownership and prevents two live processes from entering the runner
  at the same time.

Deadline contract: the Phase 3B runner cannot be force-cancelled, so this
coordinator implements a **cooperative** bounded deadline only.  It validates
the budget before invocation, passes an explicit deadline/cancellation context
when the injected runner accepts one, re-checks elapsed time immediately after
the runner returns and classifies a late completion as ``DEADLINE_EXCEEDED``
without reporting its result as success.  It never starts a worker, task, timer
or signal handler and never claims hard process termination.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import monotonic as _monotonic
from typing import Any, Callable, Literal, Mapping

from pydantic import Field, field_validator

from .monitoring_models import Contract, Count, Token, aware
from .monitoring_trigger_models import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    TriggerRequest,
    evaluate_execution_budget,
    request_fingerprint,
)
from .monitoring_trigger_ownership import (
    MonitoringTriggerOwnership,
    MonitoringTriggerOwnershipCoordinator,
)
from .monitoring_trigger_security import (
    TRIGGER_CAPABILITY,
    TRIGGER_PERSIST_CAPABILITY,
    TriggerFlagsEvaluation,
    authorize,
    evaluate_trigger_flags,
)

COORDINATOR_SCHEMA_VERSION = "supervisor-trigger-coordinator-v1"
RUNNER_CONTEXT_SCHEMA_VERSION = "supervisor-trigger-runner-context-v1"
COORDINATOR_AUDIT_SCHEMA_VERSION = "supervisor-trigger-coordinator-audit-v1"

DEFAULT_OPERATION = "SUPERVISOR_MONITORING_RUN_ONCE"
DEFAULT_MAX_DURATION_SECONDS = 60.0

# Explicit, truthful safety declarations (never weakened to obtain a pass).
COOPERATIVE_DEADLINE = "YES"
HARD_PROCESS_TERMINATION = "NO"
NEW_IDEMPOTENCY_AUTHORITY = "NO"
SQLITE_IDEMPOTENCY_REUSED = "YES"
OS_ADVISORY_LOCK_REUSED = "YES"
API_ROUTE_CONNECTED = "NO"
PRODUCTION_ACTIVATION_ALLOWED = False
DEFAULT_ENABLED = "NO"
PRODUCTION_AUTHORIZATION_SOURCE = "UNRESOLVED"
POST_ROUTE_IMPLEMENTATION_GATE = "BLOCKED"
CROSS_PROCESS_SAFETY = "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED"

CoordinatorOutcome = Literal[
    "DISABLED",
    "UNAUTHORIZED",
    "INVALID_REQUEST",
    "CLAIMED",
    "IN_PROGRESS",
    "REPLAYED",
    "IDEMPOTENCY_CONFLICT",
    "OWNERSHIP_BUSY",
    "OWNERSHIP_FAILURE",
    "STALE_GENERATION_REJECTED",
    "RUNNER_SUCCEEDED",
    "RUNNER_FAILED",
    "DEADLINE_EXCEEDED",
    "PERSISTENCE_FAILURE",
    "INTERNAL_FAILURE",
]

_CLAIM_PROCEED = frozenset({"CLAIM_ACQUIRED", "RETRY_ALLOWED", "EXPIRED_RECLAIMED"})
_CLAIM_AUTHORITY_DOWN = frozenset({"AUTHORITY_UNAVAILABLE", "CORRUPT"})

_RUNNER_FAILURE_STATUSES = frozenset(
    {"FAILED", "UNAVAILABLE", "INVALID", "DISABLED", "SKIPPED_OVERLAP", "ERROR"}
)

# Only bounded, non-secret runner-result fields are ever projected/persisted.
_RESPONSE_FIELDS = (
    "status",
    "run_id",
    "observation_count",
    "evaluation_count",
    "anomaly_count",
    "active_anomaly_count",
    "state_event_count",
    "persisted_event_count",
    "persistence_status",
    "corruption_count",
    "partial_result",
    "source_freshness",
    "source_availability",
)

_REQUIRED_STORE_METHODS = (
    "claim",
    "get_record",
    "mark_running",
    "complete_success",
    "complete_failure_retryable",
    "complete_failure_final",
)

_MAX_WARNINGS = 32


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _derive_run_id(request_id: str, generation: int) -> str:
    payload = f"{request_id}:{generation}"
    return "R" + sha256(payload.encode("utf-8")).hexdigest()[:31]


def _runner_accepts_context(runner: Callable[..., Any]) -> bool:
    """Detect, by signature only, whether the runner accepts a context argument."""

    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind is parameter.VAR_POSITIONAL:
            return True
        if parameter.name in ("context", "runner_context", "invocation_context", "deadline"):
            return True
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2


def _is_contract(value: Any) -> bool:
    return isinstance(value, Contract) or (
        hasattr(value, "model_dump") and callable(getattr(value, "model_dump"))
    )


class RunnerInvocationContext(Contract):
    """Bounded, explicit cooperative deadline/cancellation context.

    ``cooperative_deadline`` is always true and
    ``hard_cancellation_supported`` is always false: this is advisory budget
    information, not process termination authority.
    """

    schema_version: Token = RUNNER_CONTEXT_SCHEMA_VERSION
    request_id: Token
    run_id: Token
    operation: Token
    generation: Count
    owner_id: Token | None = None
    issued_at: datetime
    deadline_at: datetime
    max_duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    cooperative_deadline: bool = True
    hard_cancellation_supported: bool = False
    cancellation_requested: bool = False

    _aware = field_validator("issued_at", "deadline_at")(aware)


class CoordinatorResult(Contract):
    """Bounded, sanitized coordinator outcome.  No paths, statements or secrets."""

    schema_version: Token = COORDINATOR_SCHEMA_VERSION
    outcome: CoordinatorOutcome
    reason_code: Token = "UNKNOWN"
    request_id: Token | None = None
    run_id: Token | None = None
    operation: Token | None = None
    generation: Count | None = None
    owner_id: Token | None = None
    fingerprint: Token | None = None
    replay: bool = False
    executed: bool = False
    runner_invoked: bool = False
    runner_succeeded: bool = False
    deadline_exceeded: bool = False
    cooperative_deadline: bool = True
    hard_cancellation_supported: bool = False
    ownership_acquired: bool = False
    ownership_released: bool = True
    persisted: bool = False
    response: dict[str, Any] | None = None
    warnings: tuple[Token, ...] = Field(default=(), max_length=_MAX_WARNINGS)
    production_activation_allowed: bool = False
    api_route_connected: bool = False
    idempotency_authority: Token = "SQLITE_IDEMPOTENCY_GENERATION"
    ownership_authority: Token = "OS_ADVISORY_FLOCK"

    @field_validator("warnings")
    @classmethod
    def _ordered_warnings(cls, value):
        return tuple(sorted(set(value)))

    def to_audit(self, *, moment: datetime | None = None) -> "CoordinatorAudit":
        """Project a bounded, sanitized audit record from this result."""

        return CoordinatorAudit(
            outcome=self.outcome,
            reason_code=self.reason_code,
            request_id=self.request_id,
            operation=self.operation,
            fingerprint=self.fingerprint,
            generation=self.generation,
            run_id=self.run_id,
            runner_result=self.outcome,
            idempotency_result=self.outcome,
            completed_at=moment,
        )


class CoordinatorAudit(Contract):
    """Bounded, sanitized audit projection.  Never a durable write by itself."""

    schema_version: Token = COORDINATOR_AUDIT_SCHEMA_VERSION
    outcome: CoordinatorOutcome
    reason_code: Token
    request_id: Token | None = None
    operation: Token | None = None
    fingerprint: Token | None = None
    generation: Count | None = None
    run_id: Token | None = None
    authorization_result: Token = "NOT_EVALUATED"
    api_flag_result: Token = "NOT_EVALUATED"
    monitoring_flag_result: Token = "NOT_EVALUATED"
    idempotency_result: Token = "NOT_EVALUATED"
    ownership_result: Token = "NOT_EVALUATED"
    execution_budget_result: Token = "NOT_EVALUATED"
    runner_result: Token = "NOT_EVALUATED"
    persistence_result: Token = "NOT_EVALUATED"
    completed_at: datetime | None = None
    warnings: tuple[Token, ...] = Field(default=(), max_length=_MAX_WARNINGS)

    _aware = field_validator("completed_at")(
        lambda value: None if value is None else aware(value)
    )

    @field_validator("warnings")
    @classmethod
    def _ordered_warnings(cls, value):
        return tuple(sorted(set(value)))


class MonitoringTriggerCoordinator:
    """Compose trigger security, SQLite idempotency, the OS lock and a runner.

    The constructor is side-effect free.  All dependencies are explicit and
    injected; there is no Production default database or lock path.
    """

    def __init__(
        self,
        *,
        ownership: MonitoringTriggerOwnership,
        store: Any,
        runner: Callable[..., Any],
        operation: str = DEFAULT_OPERATION,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        default_max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
    ) -> None:
        if not isinstance(ownership, MonitoringTriggerOwnership):
            raise TypeError("ownership must be a MonitoringTriggerOwnership")
        for method in _REQUIRED_STORE_METHODS:
            if not callable(getattr(store, method, None)):
                raise TypeError(f"store must expose an explicit {method} method")
        if not callable(runner):
            raise TypeError("an explicit callable runner dependency is required")
        if not isinstance(operation, str) or not operation:
            raise TypeError("operation must be non-empty text")
        duration = float(default_max_duration_seconds)
        if not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
            raise ValueError("default_max_duration_seconds out of range")

        self._ownership = ownership
        self._store = store
        self._runner = runner
        self._operation = operation
        self._clock = clock if clock is not None else _utcnow
        self._monotonic = monotonic if monotonic is not None else _monotonic
        self._default_duration = duration
        self._runner_accepts_context = _runner_accepts_context(runner)
        self._fencing = MonitoringTriggerOwnershipCoordinator(
            ownership=ownership, store=store
        )

    # -- introspection -------------------------------------------------------

    @property
    def ownership(self) -> MonitoringTriggerOwnership:
        return self._ownership

    @property
    def store(self) -> Any:
        return self._store

    @property
    def operation(self) -> str:
        return self._operation

    @property
    def runner_accepts_context(self) -> bool:
        return self._runner_accepts_context

    # -- bounded result helper ----------------------------------------------

    @staticmethod
    def _result(outcome: CoordinatorOutcome, reason: str, **fields: Any) -> CoordinatorResult:
        clean = {key: value for key, value in fields.items()}
        clean["outcome"] = outcome
        clean["reason_code"] = reason[:128] if reason else "UNKNOWN"
        return CoordinatorResult(**clean)

    # -- feature flag / authorization ---------------------------------------

    def _resolve_flags(
        self,
        feature_flags: TriggerFlagsEvaluation | None,
        api_raw: str | None,
        monitoring_raw: str | None,
    ) -> TriggerFlagsEvaluation:
        if feature_flags is None:
            return evaluate_trigger_flags(api_raw=api_raw, monitoring_raw=monitoring_raw)
        if not isinstance(feature_flags, TriggerFlagsEvaluation):
            feature_flags = TriggerFlagsEvaluation.model_validate(feature_flags)
        return feature_flags

    # -- runner invocation ---------------------------------------------------

    def _invoke_runner(self, request: TriggerRequest, context: RunnerInvocationContext) -> Any:
        if self._runner_accepts_context:
            return self._runner(request, context)
        return self._runner(request)

    @staticmethod
    def _project_response(raw: Any) -> tuple[bool, dict[str, Any] | None]:
        """Bounded projection of an injected runner result; never the raw object."""

        if raw is None:
            return True, None
        if _is_contract(raw):
            payload = raw.model_dump(mode="json")
        elif isinstance(raw, Mapping):
            payload = dict(raw)
        else:
            return True, None

        status = payload.get("status")
        if status is not None and str(status).upper() in _RUNNER_FAILURE_STATUSES:
            return False, None
        projected: dict[str, Any] = {}
        for key in _RESPONSE_FIELDS:
            if key in payload:
                projected[key] = payload[key]
        return True, (projected or None)

    # -- terminal idempotency writes ----------------------------------------

    def _mark_failure(
        self,
        *,
        key: str,
        scope: str,
        fingerprint: str,
        generation: int,
        owner_id: str,
        error_class: str,
        retryable: bool,
        moment: datetime,
    ):
        method = (
            self._store.complete_failure_retryable
            if retryable
            else self._store.complete_failure_final
        )
        try:
            return method(
                key=key,
                operation=self._operation,
                principal_scope=scope,
                request_fingerprint=fingerprint,
                expected_generation=generation,
                owner_id=owner_id,
                error_class=error_class,
                now=moment,
            )
        except Exception:  # noqa: BLE001 - persistence failure must fail closed
            return None

    # -- main entry point ----------------------------------------------------

    def coordinate(
        self,
        *,
        request: TriggerRequest | Mapping,
        authorization: Any,
        principal_scope: str | None = None,
        feature_flags: TriggerFlagsEvaluation | None = None,
        api_raw: str | None = None,
        monitoring_raw: str | None = None,
        max_duration_seconds: float | None = None,
        claim_only: bool = False,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> CoordinatorResult:
        """Run the bounded fenced trigger pipeline and return a bounded result."""

        moment = aware(now) if now is not None else aware(self._clock())
        monotonic_start = self._monotonic()

        # 1. feature flag (API + monitoring, both default OFF, fail closed).
        try:
            flags = self._resolve_flags(feature_flags, api_raw, monitoring_raw)
        except Exception:  # noqa: BLE001 - malformed configuration fails closed
            return self._result("DISABLED", "FLAG_INVALID")
        if not flags.both_enabled:
            reason = flags.reason_code if flags.reason_code else "FLAG_DISABLED"
            return self._result("DISABLED", reason)

        # 2. bounded request validation.
        try:
            request_model = (
                request
                if isinstance(request, TriggerRequest)
                else TriggerRequest.model_validate(request)
            )
        except Exception:  # noqa: BLE001 - invalid request fails closed
            return self._result("INVALID_REQUEST", "REQUEST_INVALID")

        # 3. authorization decision (authentication alone never authorizes).
        capability = (
            TRIGGER_PERSIST_CAPABILITY
            if request_model.persistence_requested
            else TRIGGER_CAPABILITY
        )
        try:
            decision = authorize(authorization, capability=capability)
        except Exception:  # noqa: BLE001 - authorization failure fails closed
            return self._result(
                "UNAUTHORIZED", "AUTHORIZATION_ERROR",
                request_id=request_model.request_id,
            )
        if not decision.allowed:
            return self._result(
                "UNAUTHORIZED", decision.reason_code,
                request_id=request_model.request_id,
            )

        scope = principal_scope or decision.principal_ref
        if scope is None:
            return self._result(
                "INTERNAL_FAILURE", "PRINCIPAL_SCOPE_UNRESOLVED",
                request_id=request_model.request_id,
            )

        # 4. deterministic request fingerprint.
        try:
            fingerprint = request_fingerprint(request_model)
        except Exception:  # noqa: BLE001
            return self._result(
                "INVALID_REQUEST", "FINGERPRINT_FAILED",
                request_id=request_model.request_id,
            )

        duration = self._default_duration if max_duration_seconds is None else max_duration_seconds
        try:
            budget = evaluate_execution_budget(
                max_duration_seconds=duration, started_at=moment, now=moment
            )
        except Exception:  # noqa: BLE001
            return self._result(
                "INVALID_REQUEST", "DEADLINE_INVALID",
                request_id=request_model.request_id, fingerprint=fingerprint,
            )
        if budget.state != "AVAILABLE":
            return self._result(
                "INVALID_REQUEST", "DEADLINE_INVALID",
                request_id=request_model.request_id, fingerprint=fingerprint,
            )

        # 5. claim/replay through the durable SQLite idempotency authority.
        try:
            claim = self._store.claim(
                key=request_model.request_id,
                request_fingerprint=fingerprint,
                principal_scope=scope,
                operation=self._operation,
                now=moment,
            )
        except Exception:  # noqa: BLE001 - authority failure fails closed
            return self._result(
                "PERSISTENCE_FAILURE", "IDEMPOTENCY_AUTHORITY_ERROR",
                request_id=request_model.request_id, fingerprint=fingerprint,
            )
        if claim is None:
            return self._result(
                "PERSISTENCE_FAILURE", "IDEMPOTENCY_AUTHORITY_ERROR",
                request_id=request_model.request_id, fingerprint=fingerprint,
            )

        decision_name = getattr(claim, "decision", None)
        claim_reason = getattr(claim, "reason_code", "UNKNOWN") or "UNKNOWN"
        if decision_name == "REPLAY_COMPLETED":
            return self._result(
                "REPLAYED", "REPLAY",
                request_id=request_model.request_id,
                fingerprint=fingerprint,
                generation=getattr(claim, "generation", None),
                run_id=getattr(claim, "run_id", None),
                replay=True,
                response=getattr(claim, "response", None),
            )
        if decision_name == "ALREADY_IN_PROGRESS":
            return self._result(
                "IN_PROGRESS", "IN_PROGRESS",
                request_id=request_model.request_id,
                fingerprint=fingerprint,
                generation=getattr(claim, "generation", None),
                run_id=getattr(claim, "run_id", None),
            )
        if decision_name == "CONFLICT":
            return self._result(
                "IDEMPOTENCY_CONFLICT", claim_reason,
                request_id=request_model.request_id,
                fingerprint=fingerprint,
                generation=getattr(claim, "generation", None),
            )
        if decision_name in _CLAIM_AUTHORITY_DOWN:
            return self._result(
                "PERSISTENCE_FAILURE", claim_reason,
                request_id=request_model.request_id, fingerprint=fingerprint,
            )
        if decision_name not in _CLAIM_PROCEED:
            return self._result(
                "INTERNAL_FAILURE", "UNEXPECTED_CLAIM_DECISION",
                request_id=request_model.request_id, fingerprint=fingerprint,
            )

        generation = getattr(claim, "generation", None)
        owner_id = getattr(claim, "owner_id", None)
        if not isinstance(generation, int) or generation < 1 or not owner_id:
            return self._result(
                "PERSISTENCE_FAILURE", "CLAIM_ENVELOPE_INVALID",
                request_id=request_model.request_id, fingerprint=fingerprint,
            )
        resolved_run_id = run_id or _derive_run_id(request_model.request_id, generation)

        # Claim-only mode: expose CLAIMED without acquiring the OS lock or running.
        if claim_only:
            return self._result(
                "CLAIMED", "CLAIM_ACQUIRED",
                request_id=request_model.request_id,
                fingerprint=fingerprint,
                generation=generation,
                owner_id=owner_id,
                run_id=resolved_run_id,
            )

        # 6. + 7. OS advisory ownership acquisition and generation fencing.
        try:
            lease = self._fencing.acquire_for_claim(
                request_id=request_model.request_id,
                run_id=resolved_run_id,
                operation=self._operation,
                principal_scope=scope,
                request_fingerprint=fingerprint,
                expected_generation=generation,
                expected_owner_id=owner_id,
                now=moment,
            )
        except Exception:  # noqa: BLE001 - ownership failure fails closed
            self._mark_failure(
                key=request_model.request_id, scope=scope, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id,
                error_class="OWNERSHIP_FAILURE", retryable=True, moment=moment,
            )
            return self._result(
                "OWNERSHIP_FAILURE", "OWNERSHIP_ERROR",
                request_id=request_model.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id,
            )

        if not lease.acquired:
            return self._ownership_failure_result(
                lease=lease,
                request_id=request_model.request_id,
                scope=scope,
                fingerprint=fingerprint,
                generation=generation,
                owner_id=owner_id,
                moment=moment,
            )

        try:
            return self._execute_with_lease(
                request=request_model,
                scope=scope,
                fingerprint=fingerprint,
                generation=generation,
                owner_id=owner_id,
                run_id=resolved_run_id,
                moment=moment,
                monotonic_start=monotonic_start,
                duration=float(budget.max_duration_seconds),
            )
        finally:
            # 10. ownership is always released on every exit path.
            try:
                lease.release()
            except Exception:  # noqa: BLE001 - release must never raise
                pass

    def _ownership_failure_result(
        self,
        *,
        lease: Any,
        request_id: str,
        scope: str,
        fingerprint: str,
        generation: int,
        owner_id: str,
        moment: datetime,
    ) -> CoordinatorResult:
        state = getattr(lease, "state", "ERROR")
        fencing_state = getattr(lease, "fencing_state", None)
        if fencing_state in ("STALE_GENERATION", "WRONG_OWNER"):
            outcome: CoordinatorOutcome = "STALE_GENERATION_REJECTED"
            reason = fencing_state
            retryable = False
        elif state == "BUSY":
            outcome = "OWNERSHIP_BUSY"
            reason = "LOCK_BUSY"
            retryable = True
        elif fencing_state in ("RECORD_NOT_FOUND", "AUTHORITY_UNAVAILABLE"):
            outcome = "PERSISTENCE_FAILURE"
            reason = fencing_state
            retryable = True
        else:
            outcome = "OWNERSHIP_FAILURE"
            reason = "OWNERSHIP_UNAVAILABLE"
            retryable = True

        self._mark_failure(
            key=request_id, scope=scope, fingerprint=fingerprint,
            generation=generation, owner_id=owner_id,
            error_class=reason, retryable=retryable, moment=moment,
        )
        return self._result(
            outcome, reason,
            request_id=request_id, fingerprint=fingerprint,
            generation=generation, owner_id=owner_id,
        )

    def _execute_with_lease(
        self,
        *,
        request: TriggerRequest,
        scope: str,
        fingerprint: str,
        generation: int,
        owner_id: str,
        run_id: str,
        moment: datetime,
        monotonic_start: float,
        duration: float,
    ) -> CoordinatorResult:
        # Defense in depth: record the run id under the same generation.
        try:
            running = self._store.mark_running(
                key=request.request_id,
                operation=self._operation,
                principal_scope=scope,
                request_fingerprint=fingerprint,
                expected_generation=generation,
                owner_id=owner_id,
                run_id=run_id,
                now=moment,
            )
        except Exception:  # noqa: BLE001
            return self._result(
                "PERSISTENCE_FAILURE", "IDEMPOTENCY_AUTHORITY_ERROR",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, ownership_acquired=True,
                run_id=run_id,
            )
        running_decision = getattr(running, "decision", None)
        if running_decision in ("STALE_GENERATION", "WRONG_OWNER"):
            return self._result(
                "STALE_GENERATION_REJECTED", running_decision,
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, ownership_acquired=True,
                run_id=run_id,
            )
        if not getattr(running, "applied", False):
            return self._result(
                "PERSISTENCE_FAILURE",
                getattr(running, "reason_code", "RUNNING_TRANSITION_REJECTED") or "RUNNING_REJECTED",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, ownership_acquired=True,
                run_id=run_id,
            )

        # Deadline check before any runner invocation (cooperative budget only).
        if self._monotonic() - monotonic_start >= duration:
            self._mark_failure(
                key=request.request_id, scope=scope, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id,
                error_class="DEADLINE_EXCEEDED", retryable=True, moment=moment,
            )
            return self._result(
                "DEADLINE_EXCEEDED", "DEADLINE_EXCEEDED_PRE_RUNNER",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, run_id=run_id,
                ownership_acquired=True, deadline_exceeded=True,
            )

        context = RunnerInvocationContext(
            request_id=request.request_id,
            run_id=run_id,
            operation=self._operation,
            generation=generation,
            owner_id=owner_id,
            issued_at=moment,
            deadline_at=moment + timedelta(seconds=duration),
            max_duration_seconds=duration,
        )

        # 8. invoke the injected runner only after every gate has passed.
        try:
            raw = self._invoke_runner(request, context)
        except Exception:  # noqa: BLE001 - runner failure never converts to success
            self._mark_failure(
                key=request.request_id, scope=scope, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id,
                error_class="RUNNER_EXCEPTION", retryable=True, moment=moment,
            )
            return self._result(
                "RUNNER_FAILED", "RUNNER_EXCEPTION",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, run_id=run_id,
                ownership_acquired=True, runner_invoked=True, executed=True,
            )

        # Elapsed time is re-checked immediately after the runner returns.
        if self._monotonic() - monotonic_start > duration:
            self._mark_failure(
                key=request.request_id, scope=scope, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id,
                error_class="DEADLINE_EXCEEDED", retryable=False, moment=moment,
            )
            return self._result(
                "DEADLINE_EXCEEDED", "DEADLINE_EXCEEDED_LATE",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, run_id=run_id,
                ownership_acquired=True, runner_invoked=True, executed=True,
                deadline_exceeded=True,
            )

        ok, response = self._project_response(raw)
        if not ok:
            self._mark_failure(
                key=request.request_id, scope=scope, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id,
                error_class="RUNNER_STATUS_FAILED", retryable=True, moment=moment,
            )
            return self._result(
                "RUNNER_FAILED", "RUNNER_STATUS_FAILED",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, run_id=run_id,
                ownership_acquired=True, runner_invoked=True, executed=True,
            )

        # 9. persist the terminal result under the same generation/owner.
        try:
            terminal = self._store.complete_success(
                key=request.request_id,
                operation=self._operation,
                principal_scope=scope,
                request_fingerprint=fingerprint,
                expected_generation=generation,
                owner_id=owner_id,
                response=response,
                now=moment,
            )
        except Exception:  # noqa: BLE001
            return self._result(
                "PERSISTENCE_FAILURE", "IDEMPOTENCY_AUTHORITY_ERROR",
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, run_id=run_id,
                ownership_acquired=True, runner_invoked=True, executed=True,
                runner_succeeded=True,
            )

        terminal_decision = getattr(terminal, "decision", None)
        if not getattr(terminal, "applied", False):
            if terminal_decision in ("STALE_GENERATION", "WRONG_OWNER"):
                return self._result(
                    "STALE_GENERATION_REJECTED", terminal_decision,
                    request_id=request.request_id, fingerprint=fingerprint,
                    generation=generation, owner_id=owner_id, run_id=run_id,
                    ownership_acquired=True, runner_invoked=True, executed=True,
                )
            return self._result(
                "PERSISTENCE_FAILURE",
                (getattr(terminal, "reason_code", None) or "TERMINAL_PERSISTENCE_FAILURE"),
                request_id=request.request_id, fingerprint=fingerprint,
                generation=generation, owner_id=owner_id, run_id=run_id,
                ownership_acquired=True, runner_invoked=True, executed=True,
                runner_succeeded=True,
            )

        return self._result(
            "RUNNER_SUCCEEDED", "COMPLETED",
            request_id=request.request_id, fingerprint=fingerprint,
            generation=generation, owner_id=owner_id, run_id=run_id,
            ownership_acquired=True, runner_invoked=True, executed=True,
            runner_succeeded=True, persisted=True, response=response,
        )


__all__ = [
    "API_ROUTE_CONNECTED",
    "COOPERATIVE_DEADLINE",
    "COORDINATOR_AUDIT_SCHEMA_VERSION",
    "COORDINATOR_SCHEMA_VERSION",
    "CoordinatorAudit",
    "CoordinatorOutcome",
    "CoordinatorResult",
    "CROSS_PROCESS_SAFETY",
    "DEFAULT_ENABLED",
    "DEFAULT_MAX_DURATION_SECONDS",
    "DEFAULT_OPERATION",
    "HARD_PROCESS_TERMINATION",
    "MonitoringTriggerCoordinator",
    "NEW_IDEMPOTENCY_AUTHORITY",
    "OS_ADVISORY_LOCK_REUSED",
    "POST_ROUTE_IMPLEMENTATION_GATE",
    "PRODUCTION_ACTIVATION_ALLOWED",
    "PRODUCTION_AUTHORIZATION_SOURCE",
    "RunnerInvocationContext",
    "SQLITE_IDEMPOTENCY_REUSED",
]
