"""Protected Supervisor manual-trigger service (POST route core).

This service orchestrates the authenticated trigger pipeline in the mandated
fail-closed order and returns a bounded, sanitized HTTP projection.  It reuses
the completed fenced Trigger Coordinator and never bypasses the feature flag,
authorization, rate limit, bounded request validation, SQLite idempotency, OS
ownership lock, generation fencing, response sanitization or audit record.

Server configuration owns the SQLite path, ownership-lock path, retention,
timeouts and capability mapping.  A client cannot select a database path, lock
path, filesystem path, module/function name, shell command, credential, role,
capability, trading setting or order instruction.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic
from typing import Any, Callable, Mapping

from pydantic import Field

from .monitoring_models import Contract, Count, Token, aware
from .monitoring_trigger_models import TriggerRequest, request_fingerprint
from .monitoring_trigger_security import (
    TRIGGER_CAPABILITY,
    TRIGGER_PERSIST_CAPABILITY,
    AuthorizationDecision,
    TriggerFlagsEvaluation,
    principal_reference,
)
from .monitoring_trigger_coordinator import MonitoringTriggerCoordinator
from .supervisor_authorization import SupervisorAuthorizationAuthority
from .supervisor_trigger_audit import (
    SupervisorTriggerAuditRecord,
    SupervisorTriggerAuditStore,
    TriggerAuditError,
)

TRIGGER_SCHEMA_VERSION = "supervisor-trigger-http-v1"
RESTART_SAFE_IDEMPOTENCY = "SQLITE_TRANSACTIONAL"

HTTP_DISABLED = 503
HTTP_UNAUTHORIZED = 403
HTTP_RATE_LIMITED = 429
HTTP_INVALID_REQUEST = 400
HTTP_REPLAYED = 200
HTTP_CONFLICT = 409
HTTP_BUSY = 423
HTTP_SUCCESS = 200
HTTP_RUNNER_FAILED = 502
HTTP_TIMEOUT = 504
HTTP_PERSISTENCE = 500
HTTP_UNAVAILABLE = 503

_OUTCOME_HTTP: dict[str, int] = {
    "DISABLED": HTTP_DISABLED,
    "UNAUTHORIZED": HTTP_UNAUTHORIZED,
    "INVALID_REQUEST": HTTP_INVALID_REQUEST,
    "CLAIMED": HTTP_BUSY,
    "IN_PROGRESS": HTTP_BUSY,
    "REPLAYED": HTTP_REPLAYED,
    "IDEMPOTENCY_CONFLICT": HTTP_CONFLICT,
    "OWNERSHIP_BUSY": HTTP_BUSY,
    "OWNERSHIP_FAILURE": HTTP_UNAVAILABLE,
    "STALE_GENERATION_REJECTED": HTTP_CONFLICT,
    "RUNNER_SUCCEEDED": HTTP_SUCCESS,
    "RUNNER_FAILED": HTTP_RUNNER_FAILED,
    "DEADLINE_EXCEEDED": HTTP_TIMEOUT,
    "PERSISTENCE_FAILURE": HTTP_PERSISTENCE,
    "INTERNAL_FAILURE": HTTP_PERSISTENCE,
    "RATE_LIMITED": HTTP_RATE_LIMITED,
    "AUTHORIZATION_AUTHORITY_UNAVAILABLE": HTTP_UNAVAILABLE,
}
_RETRYABLE_OUTCOMES = frozenset({
    "OWNERSHIP_BUSY", "OWNERSHIP_FAILURE", "PERSISTENCE_FAILURE", "INTERNAL_FAILURE",
    "DEADLINE_EXCEEDED", "CLAIMED", "IN_PROGRESS", "RATE_LIMITED",
})


class TriggerHTTPResult(Contract):
    """Bounded, sanitized HTTP projection.  No paths, statements or secrets."""

    schema_version: Token = TRIGGER_SCHEMA_VERSION
    http_status: Count
    outcome: Token
    code: Token
    message: str = Field(min_length=1, max_length=200)
    request_id: Token | None = None
    run_id: Token | None = None
    generation: Count | None = None
    replay: bool = False
    retryable: bool = False
    audit_recorded: bool = False
    cross_process_safety: Token = "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED"
    production_activation_allowed: bool = False
    response: dict[str, Any] | None = None
    warnings: tuple[Token, ...] = Field(default=(), max_length=32)

    @classmethod
    def from_outcome(cls, outcome: str, **fields: Any) -> "TriggerHTTPResult":
        status = _OUTCOME_HTTP.get(outcome, 500)
        warnings = tuple(sorted(set(fields.pop("warnings", ()) or ())))
        message = fields.pop("message", None) or f"Supervisor monitoring trigger {outcome.lower()}."
        return cls(
            http_status=status,
            outcome=outcome,
            code=f"SUPERVISOR_MONITORING_{outcome}",
            message=message,
            retryable=outcome in _RETRYABLE_OUTCOMES,
            warnings=warnings,
            **fields,
        )


def _audit_id() -> str:
    return "T" + secrets.token_hex(16)


def _key_digest(value: str | None) -> str | None:
    if not value:
        return None
    return "K" + sha256(value.encode("utf-8")).hexdigest()[:31]


class SupervisorTriggerService:
    """Authenticated, capability-gated, rate-limited POST trigger service."""

    def __init__(
        self,
        *,
        coordinator: MonitoringTriggerCoordinator,
        authorization: SupervisorAuthorizationAuthority,
        audit_store: SupervisorTriggerAuditStore,
        rate_limiter,
        manual_trigger_enabled: Callable[[], bool] | bool,
        feature_flags: TriggerFlagsEvaluation | None = None,
        operation: str = "SUPERVISOR_MONITORING_RUN_ONCE",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(coordinator, MonitoringTriggerCoordinator):
            raise TypeError("coordinator must be a MonitoringTriggerCoordinator")
        if not isinstance(authorization, SupervisorAuthorizationAuthority):
            raise TypeError("authorization must be a SupervisorAuthorizationAuthority")
        if not isinstance(audit_store, SupervisorTriggerAuditStore):
            raise TypeError("audit_store must be a SupervisorTriggerAuditStore")
        if not callable(getattr(rate_limiter, "allow", None)):
            raise TypeError("rate_limiter must expose allow()")
        self._coordinator = coordinator
        self._authorization = authorization
        self._audit_store = audit_store
        self._rate_limiter = rate_limiter
        self._manual_enabled = manual_trigger_enabled
        self._feature_flags = feature_flags
        self._operation = operation
        self._clock = clock

    # -- helpers -------------------------------------------------------------

    def _now(self) -> datetime:
        value = self._clock() if self._clock is not None else datetime.now(timezone.utc)
        return aware(value)

    def _manual_flag_enabled(self) -> bool:
        value = self._manual_enabled
        try:
            return bool(value() if callable(value) else value)
        except Exception:  # noqa: BLE001 - malformed config fails closed
            return False

    def _audit(
        self,
        *,
        principal_id: str,
        decision: str,
        outcome: str,
        http_status: int,
        request_id: str | None,
        fingerprint: str | None,
        moment: datetime,
        replay: bool = False,
        conflict: bool = False,
        busy: bool = False,
        duration_ms: int = 0,
        failure_code: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Append a sanitized audit record.  Raises TriggerAuditError on failure."""

        record = SupervisorTriggerAuditRecord(
            audit_id=_audit_id(),
            principal_ref=principal_reference(principal_id),
            capability_decision=decision,
            request_fingerprint=fingerprint,
            idempotency_key_digest=_key_digest(request_id),
            outcome=outcome,
            http_status=http_status,
            occurred_at=moment,
            duration_ms=duration_ms,
            replay=replay,
            conflict=conflict,
            busy=busy,
            correlation_id=correlation_id,
            failure_code=failure_code,
            redacted=True,
        )
        self._audit_store.append(record)
        return True

    # -- main entry point ----------------------------------------------------

    def handle(
        self,
        *,
        principal_id: str,
        body: Mapping[str, Any] | None,
        correlation_id: str | None = None,
    ) -> TriggerHTTPResult:
        moment = self._now()
        started = self._monotonic()

        if not self._authorization.configured or self._rate_limiter is None:
            self._try_audit(
                principal_id, "NOT_EVALUATED", "AUTHORIZATION_AUTHORITY_UNAVAILABLE",
                HTTP_UNAVAILABLE, None, None, moment,
                failure_code="AUTHORIZATION_AUTHORITY_UNAVAILABLE",
            )
            return TriggerHTTPResult.from_outcome(
                "AUTHORIZATION_AUTHORITY_UNAVAILABLE",
                message="Supervisor trigger authority unavailable.",
            )

        # 1. feature flag (default OFF).
        if not self._manual_flag_enabled():
            self._try_audit(
                principal_id, "NOT_EVALUATED", "DISABLED", HTTP_DISABLED, None, None,
                moment, failure_code="FLAG_OFF",
            )
            return TriggerHTTPResult.from_outcome("DISABLED", message="disabled")

        # 2. authorization for the base trigger capability (before validation).
        base_decision = self._authorization.decide(principal_id, capability=TRIGGER_CAPABILITY)
        if not base_decision.allowed:
            self._try_audit(
                principal_id, base_decision.result, "UNAUTHORIZED", HTTP_UNAUTHORIZED,
                None, None, moment, failure_code=base_decision.reason_code,
            )
            return TriggerHTTPResult.from_outcome("UNAUTHORIZED")

        # 3. rate limit.
        if not self._rate_limiter.allow(principal_id):
            self._try_audit(
                principal_id, base_decision.result, "RATE_LIMITED", HTTP_RATE_LIMITED,
                None, None, moment, failure_code="RATE_LIMITED",
            )
            return TriggerHTTPResult.from_outcome("RATE_LIMITED")

        # 4. bounded request validation.
        try:
            request_model = (
                body if isinstance(body, TriggerRequest) else TriggerRequest.model_validate(body)
            )
        except Exception:  # noqa: BLE001 - malformed request fails closed
            self._try_audit(
                principal_id, base_decision.result, "INVALID_REQUEST", HTTP_INVALID_REQUEST,
                None, None, moment, failure_code="REQUEST_INVALID",
            )
            return TriggerHTTPResult.from_outcome("INVALID_REQUEST")

        # 5. persistence requires the strictly stronger capability.
        persist_decision = base_decision
        if request_model.persistence_requested:
            persist_decision = self._authorization.decide(
                principal_id, capability=TRIGGER_PERSIST_CAPABILITY
            )
            if not persist_decision.allowed:
                self._try_audit(
                    principal_id, persist_decision.result, "UNAUTHORIZED", HTTP_UNAUTHORIZED,
                    request_model.request_id, None, moment,
                    failure_code=persist_decision.reason_code,
                )
                return TriggerHTTPResult.from_outcome(
                    "UNAUTHORIZED", request_id=request_model.request_id
                )

        fingerprint = request_fingerprint(request_model)
        authorization_input = self._authorization.build_input(principal_id)

        # Required pre-execution audit evidence; audit failure fails closed.
        try:
            self._audit(
                principal_id=principal_id, decision=base_decision.result,
                outcome="ACCEPTED_FOR_EXECUTION", http_status=HTTP_SUCCESS,
                request_id=request_model.request_id, fingerprint=fingerprint,
                moment=moment, correlation_id=correlation_id or request_model.correlation_id,
            )
        except Exception:  # noqa: BLE001
            return TriggerHTTPResult.from_outcome(
                "PERSISTENCE_FAILURE", request_id=request_model.request_id,
            )

        # 6. execute through the completed fenced coordinator.
        try:
            coordination = self._coordinator.coordinate(
                request=request_model,
                authorization=authorization_input,
                principal_scope=principal_reference(principal_id),
                feature_flags=self._feature_flags,
                now=moment,
            )
        except Exception:  # noqa: BLE001 - internal failure fails closed, sanitized
            self._try_audit(
                principal_id, base_decision.result, "INTERNAL_FAILURE", HTTP_PERSISTENCE,
                request_model.request_id, fingerprint, moment, failure_code="INTERNAL_FAILURE",
            )
            return TriggerHTTPResult.from_outcome(
                "INTERNAL_FAILURE", request_id=request_model.request_id
            )

        outcome = coordination.outcome
        result = TriggerHTTPResult.from_outcome(
            outcome,
            request_id=coordination.request_id,
            run_id=coordination.run_id,
            generation=coordination.generation,
            replay=coordination.replay,
            response=coordination.response,
        )

        duration_ms = int((self._monotonic() - started) * 1000)
        self._try_audit(
            principal_id, base_decision.result, outcome, result.http_status,
            request_model.request_id, fingerprint, moment,
            replay=coordination.replay,
            conflict=outcome in ("IDEMPOTENCY_CONFLICT", "STALE_GENERATION_REJECTED"),
            busy=outcome in ("OWNERSHIP_BUSY", "IN_PROGRESS", "CLAIMED"),
            duration_ms=duration_ms,
            failure_code=None if outcome == "RUNNER_SUCCEEDED" else outcome,
            correlation_id=correlation_id or request_model.correlation_id,
        )
        return result

    # -- internals -----------------------------------------------------------

    def _monotonic(self) -> float:
        return monotonic()

    def _try_audit(self, principal_id, decision, outcome, status, request_id, fingerprint, moment, **extra) -> bool:
        try:
            return self._audit(
                principal_id=principal_id, decision=decision, outcome=outcome,
                http_status=status, request_id=request_id, fingerprint=fingerprint,
                moment=moment, **extra,
            )
        except TriggerAuditError:
            return False


__all__ = [
    "HTTP_BUSY",
    "HTTP_CONFLICT",
    "HTTP_DISABLED",
    "HTTP_INVALID_REQUEST",
    "HTTP_RATE_LIMITED",
    "HTTP_REPLAYED",
    "HTTP_SUCCESS",
    "HTTP_UNAUTHORIZED",
    "SupervisorTriggerService",
    "TRIGGER_SCHEMA_VERSION",
    "TriggerHTTPResult",
]
