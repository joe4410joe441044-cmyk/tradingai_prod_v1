"""Pure, bounded models for the future authenticated Supervisor manual-trigger API.

This module implements deterministic contracts only:

* a bounded trigger request DTO and its versioned request fingerprint;
* pure API-idempotency decision models (no store, no restart safety);
* a fail-closed validation-order gate evaluator;
* an execution-budget/deadline model (no timer, no cancellation);
* a cross-process ownership requirement/result model (no lock file, no flock);
* a bounded, sanitized trigger-audit record model;
* bounded response/error models with a proposed HTTP classification.

Nothing here adds or wires an API route, imports ``ManualMonitoringRunner``,
executes monitoring, persists state, schedules work, sends notifications or
grants any trading authority.  Every value is caller-supplied.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .monitoring_models import Contract, Count, Token, aware

# --- bounds -----------------------------------------------------------------
REQUEST_SCHEMA_VERSION = "supervisor-trigger-request-v1"
FINGERPRINT_VERSION = "supervisor-trigger-fingerprint-v1"
AUDIT_SCHEMA_VERSION = "supervisor-trigger-audit-v1"
RESPONSE_SCHEMA_VERSION = "supervisor-trigger-response-v1"

MAX_REQUEST_BYTES = 4096
MAX_REQUEST_ID_LENGTH = 128
MAX_SYMBOLS = 8
MAX_SYMBOL_LENGTH = 32
MAX_MODES = 4
MAX_OBSERVATIONS_CAP = 128
MAX_REASON_LENGTH = 256
MAX_AUDIT_WARNINGS = 32

MIN_DURATION_SECONDS = 0.1
MAX_DURATION_SECONDS = 3600.0

ALLOWED_MODES = frozenset({"PAPER", "LIVE"})

TriggerScope = Literal["ALL", "HEALTH", "TRADING", "SELECTION"]

ResponseClassification = Literal[
    "DISABLED",
    "UNAUTHENTICATED",
    "UNAUTHORIZED",
    "CSRF_REJECTED",
    "INVALID_REQUEST",
    "IDEMPOTENCY_REPLAY",
    "IDEMPOTENCY_CONFLICT",
    "OWNERSHIP_UNAVAILABLE",
    "BUSY",
    "DEADLINE_INVALID",
    "READY_FOR_RUNNER",
    "INTERNAL_DEPENDENCY_ERROR",
]

_SECRET_MARKERS = ("API_KEY", "APIKEY", "PASSWORD", "PRIVATE_KEY", "SECRET", "BEARER")


def _sorted_unique(values) -> tuple:
    if len({v for v in values}) != len(values):
        return tuple(sorted(set(values)))
    return tuple(sorted(values))


def _bounded_comment(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("reason must be text")
    if len(value) > MAX_REASON_LENGTH:
        raise ValueError("reason is too long")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("reason must not contain control characters")
    if "/" in value or "\\" in value or "://" in value:
        raise ValueError("reason must not contain paths or URLs")
    upper = value.upper()
    if any(marker in upper for marker in _SECRET_MARKERS) or value.startswith(("sk-", "eyJ")):
        raise ValueError("reason must not contain secret-like material")
    return value


# --- bounded request --------------------------------------------------------
class TriggerRequest(Contract):
    """A bounded future trigger request.  Server-authoritative fields are absent.

    Unknown/extra fields are rejected by the frozen ``extra='forbid'`` contract,
    so a client cannot inject actor identity, authorization, CSRF, feature-flag
    or timestamp authority.
    """

    schema_version: Token = REQUEST_SCHEMA_VERSION
    request_id: Token = Field(min_length=1, max_length=MAX_REQUEST_ID_LENGTH)
    scope: TriggerScope = "ALL"
    symbols: tuple[Token, ...] = Field(default=(), max_length=MAX_SYMBOLS)
    modes: tuple[Token, ...] = Field(default=(), max_length=MAX_MODES)
    max_observations: int = Field(
        default=MAX_OBSERVATIONS_CAP, strict=True, ge=1, le=MAX_OBSERVATIONS_CAP
    )
    persistence_requested: bool = False
    expected_config_version: Token | None = None
    reason: str = Field(default="", max_length=MAX_REASON_LENGTH)
    correlation_id: Token | None = None

    _ordered = field_validator("symbols", "modes")(_sorted_unique)
    _reason = field_validator("reason")(_bounded_comment)

    @field_validator("symbols")
    @classmethod
    def _symbol_bounds(cls, values):
        for value in values:
            if len(value) > MAX_SYMBOL_LENGTH:
                raise ValueError("symbol is too long")
            if value.upper() != value:
                raise ValueError("symbol must be upper case")
        return values

    @field_validator("modes")
    @classmethod
    def _mode_allowlist(cls, values):
        unknown = [value for value in values if value not in ALLOWED_MODES]
        if unknown:
            raise ValueError("unsupported mode")
        return values

    @model_validator(mode="after")
    def _request_size(self):
        if len(self.stable_json().encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds the bounded size")
        return self


# --- request fingerprint ----------------------------------------------------
_FINGERPRINT_FIELDS = (
    "schema_version",
    "request_id",
    "scope",
    "symbols",
    "modes",
    "max_observations",
    "persistence_requested",
    "expected_config_version",
    "reason",
)


def canonical_fingerprint_payload(request: TriggerRequest | Mapping) -> str:
    """Canonical, secret-free fingerprint input.

    ``correlation_id`` and every non-request field are excluded by design; the
    bounded request DTO cannot carry credentials.  No secret can appear here.
    """

    if not isinstance(request, TriggerRequest):
        request = TriggerRequest.model_validate(request)
    payload = {"fingerprint_version": FINGERPRINT_VERSION}
    for name in _FINGERPRINT_FIELDS:
        payload[name] = getattr(request, name)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_fingerprint(request: TriggerRequest | Mapping) -> str:
    """Versioned deterministic fingerprint; field/symbol order does not matter."""

    return sha256(canonical_fingerprint_payload(request).encode("utf-8")).hexdigest()


# --- API idempotency (pure decision only) -----------------------------------
IdempotencyStoredStatus = Literal["IN_PROGRESS", "COMPLETED", "FAILED_RETRYABLE", "EXPIRED"]
IdempotencyDecision = Literal[
    "NEW",
    "REPLAY_SAME_REQUEST",
    "CONFLICT_DIFFERENT_REQUEST",
    "IN_PROGRESS",
    "COMPLETED",
    "FAILED_RETRYABLE",
    "EXPIRED",
    "AUTHORITY_UNAVAILABLE",
]

RESTART_SAFE_API_IDEMPOTENCY = "NOT_IMPLEMENTED"


class IdempotencyRecord(Contract):
    """A caller-supplied stored idempotency record.  Never written by this module."""

    key: Token
    fingerprint: Token
    status: IdempotencyStoredStatus
    created_at: datetime
    expires_at: datetime
    run_id: Token | None = None

    _aware = field_validator("created_at", "expires_at")(aware)

    @model_validator(mode="after")
    def _coherent(self):
        if self.expires_at < self.created_at:
            raise ValueError("expires_at cannot precede created_at")
        return self


class IdempotencyDecisionResult(Contract):
    decision: IdempotencyDecision
    reason_code: Token
    key: Token | None = None
    replay: bool = False
    retryable: bool = False


def evaluate_idempotency(
    *,
    key: str,
    request_fingerprint: str,
    stored: IdempotencyRecord | None,
    now: datetime,
    authority_available: bool = True,
) -> IdempotencyDecisionResult:
    """Deterministic idempotency decision.  Performs no read and no write.

    Expiry is inclusive at the boundary (``now >= expires_at`` is EXPIRED) so the
    result is fail closed and reproducible.  Restart safety is NOT provided.
    """

    if not authority_available:
        return IdempotencyDecisionResult(
            decision="AUTHORITY_UNAVAILABLE", reason_code="IDEMPOTENCY_AUTHORITY_UNAVAILABLE",
            key=key,
        )
    if stored is None:
        return IdempotencyDecisionResult(decision="NEW", reason_code="NEW_REQUEST", key=key)
    if stored.fingerprint != request_fingerprint:
        return IdempotencyDecisionResult(
            decision="CONFLICT_DIFFERENT_REQUEST",
            reason_code="FINGERPRINT_MISMATCH", key=key,
        )
    if aware(now) >= stored.expires_at:
        return IdempotencyDecisionResult(
            decision="EXPIRED", reason_code="IDEMPOTENCY_EXPIRED", key=key,
        )
    if stored.status == "IN_PROGRESS":
        return IdempotencyDecisionResult(
            decision="IN_PROGRESS", reason_code="IN_PROGRESS", key=key,
        )
    if stored.status == "COMPLETED":
        return IdempotencyDecisionResult(
            decision="REPLAY_SAME_REQUEST", reason_code="REPLAY", key=key, replay=True,
        )
    if stored.status == "FAILED_RETRYABLE":
        return IdempotencyDecisionResult(
            decision="FAILED_RETRYABLE", reason_code="RETRYABLE", key=key, retryable=True,
        )
    return IdempotencyDecisionResult(
        decision="EXPIRED", reason_code="IDEMPOTENCY_EXPIRED", key=key,
    )


# --- validation-order gate model --------------------------------------------
VALIDATION_GATE_ORDER: tuple[str, ...] = (
    "ROUTE_ENABLED",
    "AUTHENTICATION",
    "AUTHORIZATION",
    "CSRF",
    "REQUEST_VALIDATION",
    "IDEMPOTENCY",
    "CROSS_PROCESS_OWNERSHIP",
    "IN_PROCESS_OVERLAP",
    "EXECUTION_BUDGET",
    "RUNNER_ELIGIBILITY",
)
GateName = Literal[
    "ROUTE_ENABLED",
    "AUTHENTICATION",
    "AUTHORIZATION",
    "CSRF",
    "REQUEST_VALIDATION",
    "IDEMPOTENCY",
    "CROSS_PROCESS_OWNERSHIP",
    "IN_PROCESS_OVERLAP",
    "EXECUTION_BUDGET",
    "RUNNER_ELIGIBILITY",
]
GateStatus = Literal["ALLOW", "BLOCK", "NOT_EVALUATED"]

_GATE_CLASSIFICATION: dict[str, str] = {
    "ROUTE_ENABLED": "DISABLED",
    "AUTHENTICATION": "UNAUTHENTICATED",
    "AUTHORIZATION": "UNAUTHORIZED",
    "CSRF": "CSRF_REJECTED",
    "REQUEST_VALIDATION": "INVALID_REQUEST",
    "IDEMPOTENCY": "IDEMPOTENCY_CONFLICT",
    "CROSS_PROCESS_OWNERSHIP": "OWNERSHIP_UNAVAILABLE",
    "IN_PROCESS_OVERLAP": "BUSY",
    "EXECUTION_BUDGET": "DEADLINE_INVALID",
    "RUNNER_ELIGIBILITY": "INTERNAL_DEPENDENCY_ERROR",
}


class GateDecision(Contract):
    gate: GateName
    status: GateStatus
    reason_code: Token = "OK"


class GateOrderResult(Contract):
    """First blocking gate plus an explicit NOT_EVALUATED record for the rest."""

    first_blocking_gate: GateName | None = None
    ready_for_runner: bool = False
    classification: ResponseClassification = "READY_FOR_RUNNER"
    gates: tuple[GateDecision, ...]


def evaluate_gate_order(
    gates: Mapping[str, "GateDecision | str"] | None = None,
) -> GateOrderResult:
    """Fail-closed gate ordering.  Never calls the runner or any dependency.

    Gates not present in ``gates`` default to ALLOW; every gate after the first
    BLOCK is recorded as NOT_EVALUATED (skipped).
    """

    supplied = dict(gates or {})
    results: list[GateDecision] = []
    first: str | None = None
    for name in VALIDATION_GATE_ORDER:
        if first is not None:
            results.append(GateDecision(gate=name, status="NOT_EVALUATED", reason_code="SKIPPED"))
            continue
        raw = supplied.get(name)
        if raw is None:
            decision = GateDecision(gate=name, status="ALLOW", reason_code="OK")
        elif isinstance(raw, GateDecision):
            if raw.gate != name:
                raise ValueError("gate decision does not match its position")
            decision = raw
        else:
            status = str(raw).upper()
            if status not in ("ALLOW", "BLOCK"):
                raise ValueError("gate status must be ALLOW or BLOCK")
            decision = GateDecision(
                gate=name, status=status,
                reason_code="OK" if status == "ALLOW" else name,
            )
        if decision.status == "BLOCK":
            first = name
        results.append(decision)

    classification: str = _GATE_CLASSIFICATION[first] if first else "READY_FOR_RUNNER"
    return GateOrderResult(
        first_blocking_gate=first,
        ready_for_runner=first is None,
        classification=classification,  # type: ignore[arg-type]
        gates=tuple(results),
    )


# --- execution budget -------------------------------------------------------
BudgetState = Literal["AVAILABLE", "EXPIRED", "INVALID"]


class ExecutionBudgetResult(Contract):
    state: BudgetState
    reason_code: Token
    max_duration_seconds: float | None = None
    started_at: datetime | None = None
    deadline_at: datetime | None = None
    remaining_seconds: float | None = None

    _aware = field_validator("started_at", "deadline_at")(
        lambda value: None if value is None else aware(value)
    )


def _invalid_budget(reason: str) -> ExecutionBudgetResult:
    return ExecutionBudgetResult(state="INVALID", reason_code=reason)


def evaluate_execution_budget(
    *,
    max_duration_seconds,
    started_at,
    now,
) -> ExecutionBudgetResult:
    """Deterministic deadline projection.  No timer, thread, task or signal.

    The deadline is ``started_at + max_duration_seconds``.  At the exact
    boundary (``now == deadline_at``) the budget is EXPIRED (fail closed).
    """

    try:
        duration = float(max_duration_seconds)
    except (TypeError, ValueError):
        return _invalid_budget("DURATION_MALFORMED")
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_DURATION_SECONDS:
        return _invalid_budget("DURATION_OUT_OF_RANGE")
    try:
        start = aware(started_at)
        current = aware(now)
    except Exception:
        return _invalid_budget("TIMESTAMP_INVALID")

    deadline = start + timedelta(seconds=duration)
    expired = current >= deadline
    remaining = max(0.0, (deadline - current).total_seconds())
    return ExecutionBudgetResult(
        state="EXPIRED" if expired else "AVAILABLE",
        reason_code="DEADLINE_EXPIRED" if expired else "DEADLINE_AVAILABLE",
        max_duration_seconds=duration,
        started_at=start,
        deadline_at=deadline,
        remaining_seconds=remaining,
    )


# --- cross-process ownership ------------------------------------------------
OwnershipState = Literal[
    "NOT_CONFIGURED",
    "AVAILABLE",
    "ACQUIRED",
    "BUSY",
    "STALE_METADATA",
    "ERROR",
    "UNSUPPORTED",
]
CROSS_PROCESS_MECHANISM = "OS_ADVISORY_EXCLUSIVE_LOCK"
CROSS_PROCESS_SAFETY = "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED"
OS_ADVISORY_LOCK_IMPLEMENTED = "NO"
PRODUCTION_ACTIVATION_ALLOWED = False


class OwnershipRequirement(Contract):
    required: bool = True
    mechanism: Token = CROSS_PROCESS_MECHANISM
    lock_configured: bool = False
    single_process_asserted: bool = False


class OwnershipResult(Contract):
    state: OwnershipState
    reason_code: Token
    required: bool = True
    mechanism: Token = CROSS_PROCESS_MECHANISM
    lock_path_configured: bool = False
    acquired: bool = False
    fencing_token: Token | None = None
    production_activation_allowed: bool = False


# --- sanitized audit record -------------------------------------------------
PersistenceMode = Literal["NONE", "DRY_RUN", "PERSIST_REQUESTED"]

_FORBIDDEN_AUDIT_KEYS = frozenset({
    "password", "api_key", "apikey", "authorization", "authorization_header",
    "cookie", "cookies", "session", "session_token", "session_id", "csrf",
    "csrf_token", "token", "secret", "raw_body", "raw_request", "raw_evidence",
    "evidence", "trace", "stack_trace", "traceback", "exception",
})


class TriggerAuditRecord(Contract):
    """Bounded, sanitized trigger-audit record.  Never written by this module."""

    schema_version: Token = AUDIT_SCHEMA_VERSION
    audit_event_id: Token
    request_id: Token | None = None
    principal_ref: Token | None = None
    authentication_result: Token = "NOT_EVALUATED"
    authorization_result: Token = "NOT_EVALUATED"
    csrf_result: Token = "NOT_EVALUATED"
    api_flag_result: Token = "NOT_EVALUATED"
    monitoring_flag_result: Token = "NOT_EVALUATED"
    request_fingerprint: Token | None = None
    idempotency_result: Token = "NOT_EVALUATED"
    ownership_result: Token = "NOT_EVALUATED"
    overlap_result: Token = "NOT_EVALUATED"
    execution_budget_result: Token = "NOT_EVALUATED"
    persistence_mode: PersistenceMode = "NONE"
    result_classification: Token = "UNKNOWN"
    error_code: Token | None = None
    received_at: datetime
    completed_at: datetime | None = None
    redacted: bool = False
    warnings: tuple[Token, ...] = Field(default=(), max_length=MAX_AUDIT_WARNINGS)

    _aware = field_validator("received_at", "completed_at")(
        lambda value: None if value is None else aware(value)
    )

    @field_validator("warnings")
    @classmethod
    def _warnings(cls, values):
        if len(values) > MAX_AUDIT_WARNINGS:
            raise ValueError("too many audit warnings")
        return _sorted_unique(values)

    @classmethod
    def from_mapping(cls, data: Mapping) -> "TriggerAuditRecord":
        """Build a record, redacting forbidden keys instead of persisting them."""

        payload = dict(data)
        redacted = [key for key in payload if str(key).lower() in _FORBIDDEN_AUDIT_KEYS]
        for key in redacted:
            payload.pop(key, None)
        warnings = list(payload.get("warnings", ()))
        if redacted:
            payload["redacted"] = True
            warnings.append("FORBIDDEN_KEY_REDACTED")
        payload["warnings"] = tuple(sorted(set(warnings)))
        return cls.model_validate(payload)


# --- response / error models ------------------------------------------------
_RESPONSE_HTTP: dict[str, int] = {
    "DISABLED": 503,
    "UNAUTHENTICATED": 401,
    "UNAUTHORIZED": 403,
    "CSRF_REJECTED": 403,
    "INVALID_REQUEST": 400,
    "IDEMPOTENCY_REPLAY": 200,
    "IDEMPOTENCY_CONFLICT": 409,
    "OWNERSHIP_UNAVAILABLE": 503,
    "BUSY": 409,
    "DEADLINE_INVALID": 504,
    "READY_FOR_RUNNER": 200,
    "INTERNAL_DEPENDENCY_ERROR": 500,
}
_RESPONSE_MESSAGE: dict[str, str] = {
    "DISABLED": "Supervisor monitoring trigger is disabled.",
    "UNAUTHENTICATED": "Operator authentication is required.",
    "UNAUTHORIZED": "Operator capability is required.",
    "CSRF_REJECTED": "Request rejected.",
    "INVALID_REQUEST": "Request is invalid.",
    "IDEMPOTENCY_REPLAY": "Request replayed from an earlier identical request.",
    "IDEMPOTENCY_CONFLICT": "Request conflicts with an earlier request.",
    "OWNERSHIP_UNAVAILABLE": "Monitoring ownership is unavailable.",
    "BUSY": "A monitoring run is already in progress.",
    "DEADLINE_INVALID": "Execution budget is unavailable.",
    "READY_FOR_RUNNER": "Request is ready for bounded execution.",
    "INTERNAL_DEPENDENCY_ERROR": "Request could not be completed.",
}
_RESPONSE_RETRYABLE = frozenset({
    "OWNERSHIP_UNAVAILABLE", "BUSY", "DEADLINE_INVALID", "INTERNAL_DEPENDENCY_ERROR",
})


class TriggerResponse(Contract):
    """Bounded sanitized response model.  No route is registered anywhere."""

    schema_version: Token = RESPONSE_SCHEMA_VERSION
    classification: ResponseClassification
    http_status: Count
    code: Token
    message: str = Field(min_length=1, max_length=200)
    retryable: bool = False
    idempotent_replay: bool = False
    request_id: Token | None = None
    cross_process_safety: Token = CROSS_PROCESS_SAFETY
    production_activation_allowed: bool = False

    @field_validator("message")
    @classmethod
    def _sanitized_message(cls, value: str) -> str:
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("message must not contain control characters")
        if "/" in value or "\\" in value or "://" in value:
            raise ValueError("message must not contain paths or URLs")
        upper = value.upper()
        if any(marker in upper for marker in _SECRET_MARKERS):
            raise ValueError("message must not contain secret-like material")
        return value


def proposed_http_status(classification: str) -> int:
    return _RESPONSE_HTTP[classification]


def build_response(
    classification: str,
    *,
    request_id: str | None = None,
    idempotent_replay: bool = False,
) -> TriggerResponse:
    """Build a bounded, sanitized response projection from a classification."""

    if classification not in _RESPONSE_HTTP:
        raise ValueError("unknown classification")
    return TriggerResponse(
        classification=classification,  # type: ignore[arg-type]
        http_status=_RESPONSE_HTTP[classification],
        code=f"SUPERVISOR_MONITORING_{classification}",
        message=_RESPONSE_MESSAGE[classification],
        retryable=classification in _RESPONSE_RETRYABLE,
        idempotent_replay=idempotent_replay and classification == "IDEMPOTENCY_REPLAY",
        request_id=request_id,
    )
