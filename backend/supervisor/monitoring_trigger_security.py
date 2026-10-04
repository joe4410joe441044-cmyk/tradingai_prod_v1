"""Pure authorization/capability and feature-flag models for the future
authenticated Supervisor manual-trigger API.

Nothing here is an implementation of the API.  These are deterministic contracts
that a future route (Phase 3D-3, separately approved) will consume:

* an explicit trigger capability contract and a fail-closed authorization
  evaluator;
* a default-OFF trigger feature-flag model that evaluates the API flag and the
  monitoring flag independently.

The constant operator identity never authorizes a request on its own.  Only an
explicitly asserted capability, sourced from an *available* and *fresh* verified
capability authority, can ALLOW.  Every uncertain state denies (fail closed).
No environment is read or mutated at import time; callers supply values
explicitly, so identical inputs yield identical outputs.

There is no Production role/capability database: PRODUCTION_AUTHORIZATION_SOURCE
is UNRESOLVED and the POST-route implementation gate remains BLOCKED.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Literal, Mapping

from pydantic import Field, field_validator

from .monitoring_models import Contract, Freshness, Token
from .monitoring_scheduler_models import FeatureFlagStatus, resolve_feature_flag_status

# Explicit trigger capabilities.  ``..._RUN_ONCE`` authorizes observation-only
# execution; ``..._PERSIST`` is the strictly stronger capability required before
# any anomaly-state persistence may be requested.
TRIGGER_CAPABILITY = "SUPERVISOR_MONITORING_RUN_ONCE"
TRIGGER_PERSIST_CAPABILITY = "SUPERVISOR_MONITORING_RUN_ONCE_PERSIST"

TRIGGER_API_ENABLED_ENV = "AI_SUPERVISOR_MANUAL_TRIGGER_API_ENABLED"
MONITORING_ENABLED_ENV = "AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED"

# The authorization contract itself is implemented here, but no canonical
# Production capability source exists in the repository.
AUTHORIZATION_MODEL = "IMPLEMENTED"
PRODUCTION_AUTHORIZATION_SOURCE = "UNRESOLVED"
POST_ROUTE_IMPLEMENTATION_GATE = "BLOCKED"

AuthorizationResult = Literal[
    "ALLOW",
    "DENY_UNAUTHENTICATED",
    "DENY_PRINCIPAL_UNRESOLVED",
    "DENY_CAPABILITY_MISSING",
    "DENY_AUTHORITY_UNAVAILABLE",
    "DENY_AUTHORITY_STALE",
    "DENY_MALFORMED_INPUT",
]
CapabilitySource = Literal["VERIFIED_ADAPTER", "UNVERIFIED", "UNAVAILABLE", "UNKNOWN"]

DENIED = frozenset({
    "DENY_UNAUTHENTICATED", "DENY_PRINCIPAL_UNRESOLVED", "DENY_CAPABILITY_MISSING",
    "DENY_AUTHORITY_UNAVAILABLE", "DENY_AUTHORITY_STALE", "DENY_MALFORMED_INPUT",
})

# Maps an authorization result to a bounded reason code (presentation safe).
_REASON_CODES = {
    "ALLOW": "AUTHORIZED",
    "DENY_UNAUTHENTICATED": "NOT_AUTHENTICATED",
    "DENY_PRINCIPAL_UNRESOLVED": "PRINCIPAL_UNRESOLVED",
    "DENY_CAPABILITY_MISSING": "CAPABILITY_MISSING",
    "DENY_AUTHORITY_UNAVAILABLE": "AUTHORITY_UNAVAILABLE",
    "DENY_AUTHORITY_STALE": "AUTHORITY_STALE",
    "DENY_MALFORMED_INPUT": "MALFORMED_AUTHORIZATION_INPUT",
}


def _sorted_unique(values) -> tuple:
    if len({v for v in values}) != len(values):
        return tuple(sorted(set(values)))
    return tuple(sorted(values))


class AuthorizationInput(Contract):
    """Explicit, caller-supplied authorization evidence.  No source is resolved."""

    authenticated: bool = False
    principal_id: Token | None = None
    roles: tuple[Token, ...] = Field(default=(), max_length=32)
    capabilities: tuple[Token, ...] = Field(default=(), max_length=64)
    capability_source: CapabilitySource = "UNKNOWN"
    source_available: bool = False
    source_freshness: Freshness = "UNKNOWN"
    source_version: Token | None = None

    _ordered = field_validator("roles", "capabilities")(_sorted_unique)


class AuthorizationDecision(Contract):
    """Bounded, sanitized authorization outcome for a single capability."""

    result: AuthorizationResult
    capability: Token
    reason_code: Token
    principal_ref: Token | None = None
    allowed: bool = False


def principal_reference(principal_id: str) -> str:
    """Privacy-safe, stable actor reference.  Never returns the raw identity."""

    return "P" + sha256(str(principal_id).encode("utf-8")).hexdigest()[:32]


def evaluate_authorization(
    candidate: AuthorizationInput | Mapping | None,
    *,
    capability: str = TRIGGER_CAPABILITY,
) -> AuthorizationResult:
    """Deterministically evaluate one capability.  Every uncertainty denies.

    The constant ``"operator"`` identity is irrelevant here: an authenticated
    principal with no explicit, verified capability is denied.  A malformed or
    missing candidate is denied as malformed input.
    """

    if isinstance(candidate, AuthorizationInput):
        value = candidate
    else:
        try:
            value = AuthorizationInput.model_validate(candidate)
        except Exception:
            return "DENY_MALFORMED_INPUT"

    if not value.authenticated:
        return "DENY_UNAUTHENTICATED"
    if not value.principal_id:
        return "DENY_PRINCIPAL_UNRESOLVED"
    if not value.source_available or value.capability_source == "UNAVAILABLE":
        return "DENY_AUTHORITY_UNAVAILABLE"
    if value.source_freshness == "STALE":
        return "DENY_AUTHORITY_STALE"
    if value.capability_source != "VERIFIED_ADAPTER":
        # UNVERIFIED / UNKNOWN sources cannot authorize, even with a claimed
        # capability, so a bare authenticated session never becomes authorized.
        return "DENY_AUTHORITY_UNAVAILABLE"
    if capability not in value.capabilities:
        return "DENY_CAPABILITY_MISSING"
    return "ALLOW"


def authorize(
    candidate: AuthorizationInput | Mapping | None,
    *,
    capability: str = TRIGGER_CAPABILITY,
) -> AuthorizationDecision:
    """Return a bounded authorization decision for one capability."""

    result = evaluate_authorization(candidate, capability=capability)
    principal_ref = None
    if result != "DENY_MALFORMED_INPUT":
        value = candidate if isinstance(candidate, AuthorizationInput) else None
        if value is None:
            try:
                value = AuthorizationInput.model_validate(candidate)
            except Exception:
                value = None
        if value is not None and value.principal_id:
            principal_ref = principal_reference(value.principal_id)
    return AuthorizationDecision(
        result=result, capability=capability, reason_code=_REASON_CODES[result],
        principal_ref=principal_ref, allowed=result == "ALLOW",
    )


class TriggerFlagsEvaluation(Contract):
    """Separate, fail-closed evaluation of the API flag and the monitoring flag."""

    api_flag: FeatureFlagStatus
    monitoring_flag: FeatureFlagStatus
    api_enabled: bool
    monitoring_enabled: bool
    both_enabled: bool
    reason_code: Token


def resolve_trigger_flag(raw_value: str | None) -> FeatureFlagStatus:
    """Resolve the API flag from an already-read raw value; fail closed.

    Reading the environment is the caller's responsibility.  Absent, empty or
    falsy values are disabled; malformed values are disabled and marked invalid.
    """

    return resolve_feature_flag_status(raw_value)


def evaluate_trigger_flags(
    *,
    api_raw: str | None = None,
    monitoring_raw: str | None = None,
) -> TriggerFlagsEvaluation:
    """Evaluate both gates independently; both must be enabled to proceed."""

    api_flag = resolve_trigger_flag(api_raw)
    monitoring_flag = resolve_trigger_flag(monitoring_raw)

    if not api_flag.valid or not monitoring_flag.valid:
        reason_code = "FLAG_INVALID"
    elif not api_flag.enabled:
        reason_code = "FLAG_OFF_API"
    elif not monitoring_flag.enabled:
        reason_code = "FLAG_OFF_MONITORING"
    else:
        reason_code = "FLAGS_READY"

    return TriggerFlagsEvaluation(
        api_flag=api_flag,
        monitoring_flag=monitoring_flag,
        api_enabled=api_flag.enabled,
        monitoring_enabled=monitoring_flag.enabled,
        both_enabled=api_flag.enabled and monitoring_flag.enabled,
        reason_code=reason_code,
    )


def evaluate_trigger_flags_from_environ(
    environ: Mapping[str, str],
) -> TriggerFlagsEvaluation:
    """Evaluate both gates from an injected mapping (no global environment read)."""

    return evaluate_trigger_flags(
        api_raw=environ.get(TRIGGER_API_ENABLED_ENV),
        monitoring_raw=environ.get(MONITORING_ENABLED_ENV),
    )
