# -*- coding: utf-8 -*-
"""Explicit runtime-state contracts for operator-facing diagnostics.

These helpers are pure projections.  They never construct exchange clients,
call an exchange, start/stop a loop, mutate readiness, or write runtime state.
Their purpose is to keep five authorities distinct instead of collapsing them
into one "running" flag:

* systemd/service process activity
* bot lifecycle state
* trading-loop state
* exchange execution authority
* durable STOPPED snapshot evidence

Unknown values stay ``UNKNOWN``.  A genuine contradiction is reported as
``INCONSISTENT`` so a caller can fail closed, but a legitimate
"bot attached / loop stopped" state is never rewritten as STOPPED.
"""

from collections.abc import Mapping


SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Durable STOPPED snapshot
# ---------------------------------------------------------------------------

SNAPSHOT_VALID = "VALID"
SNAPSHOT_MISSING = "MISSING"
SNAPSHOT_STALE = "STALE"
SNAPSHOT_INCONSISTENT = "INCONSISTENT"
SNAPSHOT_UNKNOWN = "UNKNOWN"

_SNAPSHOT_MISSING_REASONS = frozenset({
    "DURABLE_SNAPSHOT_MISSING",
})

_SNAPSHOT_STALE_REASONS = frozenset({
    "DURABLE_SNAPSHOT_STALE",
    "SNAPSHOT_STALE",
    "SNAPSHOT_STALE_THRESHOLD_INVALID",
    "SNAPSHOT_REQUIRED_FIELD_MISSING",
    "DURABLE_SNAPSHOT_FIELD_MISSING",
})

_SNAPSHOT_INCONSISTENT_REASONS = frozenset({
    "DURABLE_SNAPSHOT_LIFECYCLE_MISMATCH",
    "MODE_UNKNOWN",
    "SNAPSHOT_SOURCE_MISMATCH",
    "SNAPSHOT_SOURCE_UNKNOWN",
    "DURABLE_RUNTIME_INSTANCE_CURRENT",
    "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
    "SNAPSHOT_GENERATION_MISMATCH",
    "SNAPSHOT_TIMESTAMP_FUTURE",
    "SNAPSHOT_TIMESTAMP_INVALID",
    "OPEN_ORDER_SOURCE_MISMATCH",
    "POSITION_STATE_UNKNOWN",
    "PENDING_ORDER_UNKNOWN",
    "OPEN_ORDER_UNKNOWN",
})

_SNAPSHOT_UNREADABLE_REASONS = frozenset({
    "DURABLE_SNAPSHOT_READ_FAILED",
    "DURABLE_SNAPSHOT_CORRUPT",
    "DURABLE_SNAPSHOT_SYMLINK_NOT_ALLOWED",
    "DURABLE_SNAPSHOT_NOT_REGULAR_FILE",
    "DURABLE_SNAPSHOT_FILE_IDENTITY_CHANGED",
    "SNAPSHOT_TIME_UNAVAILABLE",
    "STATE_UNKNOWN",
})


def classify_stopped_snapshot(status):
    """Classify an existing snapshot status without treating missing as STOPPED.

    The input is the read-only ``get_stopped_paper_snapshot_status()`` shape
    (or any mapping with ``valid`` / ``reason`` / ``durableExists``).
    """

    if not isinstance(status, Mapping):
        return _snapshot_result(
            SNAPSHOT_UNKNOWN,
            reason="SNAPSHOT_STATUS_UNAVAILABLE",
            durable_exists=None,
        )

    valid = status.get("valid")
    reason = status.get("reason")
    durable_exists = status.get("durableExists")

    if valid is True:
        state = SNAPSHOT_VALID
    elif reason in _SNAPSHOT_MISSING_REASONS:
        state = SNAPSHOT_MISSING
    elif reason in _SNAPSHOT_STALE_REASONS:
        state = SNAPSHOT_STALE
    elif reason in _SNAPSHOT_INCONSISTENT_REASONS:
        state = SNAPSHOT_INCONSISTENT
    elif reason in _SNAPSHOT_UNREADABLE_REASONS:
        state = SNAPSHOT_UNKNOWN
    elif durable_exists is False and not reason:
        state = SNAPSHOT_MISSING
    else:
        state = SNAPSHOT_UNKNOWN

    return _snapshot_result(state, reason=reason, durable_exists=durable_exists)


def _snapshot_result(state, *, reason, durable_exists):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": state,
        "reason": reason,
        "evidencePresent": durable_exists is True,
        "usableAsStoppedEvidence": state == SNAPSHOT_VALID,
        "missingIsStoppedEvidence": False,
        "staleIsStoppedEvidence": False,
    }


# ---------------------------------------------------------------------------
# Lifecycle / loop / authority boundaries
# ---------------------------------------------------------------------------

CONSISTENT = "CONSISTENT"
INCONSISTENT = "INCONSISTENT"
UNKNOWN = "UNKNOWN"

_LIFECYCLE_STATES = frozenset({
    "STOPPED",
    "STARTING",
    "RUNNING",
    "STOPPING",
})

_LOOP_STATES = frozenset({
    "STOPPED",
    "STARTING",
    "RUNNING",
    "STOPPING",
})


def _normalize_state(value):
    return str(value or "").strip().upper()


def project_lifecycle_consistency(
    *,
    bot_lifecycle_state,
    loop_state,
    engine_available=None,
    execution_authority=None,
    durable_snapshot_state=None,
    service_active=None,
):
    """Project lifecycle/loop consistency from existing authorities.

    ``bot_lifecycle_state="RUNNING"`` with ``loop_state="STOPPED"`` is a
    legitimate "bot attached, loop intentionally stopped" state.  It is
    reported as CONSISTENT (with an explicit reason) and is NOT downgraded to
    a false STOPPED.  Only a real contradiction is INCONSISTENT.
    """

    lifecycle = _normalize_state(bot_lifecycle_state)
    loop = _normalize_state(loop_state)
    snapshot_state = _normalize_state(durable_snapshot_state) or SNAPSHOT_UNKNOWN

    reasons = []
    state = CONSISTENT

    if lifecycle not in _LIFECYCLE_STATES or loop not in _LOOP_STATES:
        state = UNKNOWN
        reasons.append("LIFECYCLE_STATE_UNKNOWN")
    elif lifecycle == "STOPPED" and loop == "RUNNING":
        state = INCONSISTENT
        reasons.append("LOOP_RUNNING_WHILE_BOT_STOPPED")
    elif loop == "RUNNING" and engine_available is False:
        state = INCONSISTENT
        reasons.append("LOOP_RUNNING_WITHOUT_ENGINE")
    elif lifecycle == "RUNNING" and loop == "STOPPED":
        reasons.append("BOT_ATTACHED_LOOP_STOPPED")
    elif lifecycle in ("STARTING", "STOPPING") or loop in ("STARTING", "STOPPING"):
        reasons.append("LIFECYCLE_TRANSITIONAL")
    else:
        reasons.append("BOT_LIFECYCLE_AND_LOOP_ALIGNED")

    if snapshot_state == SNAPSHOT_INCONSISTENT:
        state = INCONSISTENT
        reasons.append("DURABLE_SNAPSHOT_INCONSISTENT")
    elif snapshot_state == SNAPSHOT_MISSING:
        # Missing evidence is surfaced, but it is not a lifecycle
        # contradiction and must never be treated as a STOPPED proof.
        reasons.append("DURABLE_SNAPSHOT_MISSING")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": state,
        "consistent": (None if state == UNKNOWN else state == CONSISTENT),
        "reasons": list(dict.fromkeys(reasons)),
        "boundaries": {
            "serviceActive": (
                service_active if isinstance(service_active, bool) else None
            ),
            "botLifecycle": lifecycle or UNKNOWN,
            "tradingLoop": loop or UNKNOWN,
            "exchangeExecutionAuthority": (
                _normalize_state(execution_authority) or UNKNOWN
            ),
            "durableStoppedSnapshot": snapshot_state,
        },
        "serviceActiveIsNotBotRunning": True,
        "durableSnapshotIsNotLoopState": True,
        "falseStoppedProjected": False,
    }


# ---------------------------------------------------------------------------
# Margin mode contract
# ---------------------------------------------------------------------------

MARGIN_MODE_ISOLATED = "ISOLATED"
MARGIN_MODE_CROSS = "CROSS"
MARGIN_MODE_UNKNOWN = "UNKNOWN"

MARGIN_STATE_COMPATIBLE = "COMPATIBLE"
MARGIN_STATE_MISMATCH = "MISMATCH"
MARGIN_STATE_UNKNOWN = "UNKNOWN"

_CANONICAL_MARGIN_MODES = frozenset({
    MARGIN_MODE_ISOLATED,
    MARGIN_MODE_CROSS,
})


def _normalize_margin_mode(value):
    normalized = str(value or "").strip().upper()
    return normalized if normalized in _CANONICAL_MARGIN_MODES else MARGIN_MODE_UNKNOWN


def project_margin_mode_contract(
    *,
    required_mode=MARGIN_MODE_ISOLATED,
    configured_mode=None,
    effective_mode=None,
    observed_mode=None,
    known=None,
    source=None,
    updated_at=None,
):
    """Keep configured / effective / observed margin mode distinct.

    Compliance uses only the exchange-observed mode versus the required mode.
    CROSS is never treated as ISOLATED, and this projection never changes the
    exchange or the required mode.
    """

    required = _normalize_margin_mode(required_mode)
    configured = _normalize_margin_mode(configured_mode)
    effective = _normalize_margin_mode(effective_mode)
    observed = _normalize_margin_mode(observed_mode)

    if known is None:
        known = observed in _CANONICAL_MARGIN_MODES

    if known is not True or observed == MARGIN_MODE_UNKNOWN:
        state = MARGIN_STATE_UNKNOWN
        compatible = None
        reason = "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    elif required == MARGIN_MODE_UNKNOWN:
        state = MARGIN_STATE_UNKNOWN
        compatible = None
        reason = "MARGIN_MODE_REQUIREMENT_UNKNOWN"
    elif observed == required:
        state = MARGIN_STATE_COMPATIBLE
        compatible = True
        reason = "MARGIN_MODE_COMPATIBLE"
    else:
        state = MARGIN_STATE_MISMATCH
        compatible = False
        reason = "MARGIN_MODE_MISMATCH"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "requiredMode": required,
        "configuredMode": configured,
        "effectiveMode": effective,
        "observedMode": observed,
        "state": state,
        "compatible": compatible,
        "reason": reason,
        "source": source,
        "updatedAt": updated_at,
        "autoChangeAllowed": False,
        "crossEqualsIsolated": False,
    }


# ---------------------------------------------------------------------------
# KuCoin permission contract
# ---------------------------------------------------------------------------

PERMISSION_READ_ONLY = "READ_ONLY"
PERMISSION_TRADE = "TRADE"
PERMISSION_WITHDRAW = "WITHDRAW"
PERMISSION_TRADE_AND_WITHDRAW = "TRADE_AND_WITHDRAW"
PERMISSION_DENIED = "DENIED"
PERMISSION_UNKNOWN = "UNKNOWN"

PERMISSION_STATUS_VERIFIED = "VERIFIED"
PERMISSION_STATUS_UNVERIFIED = "UNVERIFIED"
PERMISSION_STATUS_DENIED = "DENIED"
PERMISSION_STATUS_UNKNOWN = "UNKNOWN"

PERMISSION_AUTHORITY_VERIFIED = "TRADING_PERMISSION_VERIFIED"
PERMISSION_REASON_UNVERIFIED = "TRADING_PERMISSION_UNVERIFIED"
PERMISSION_REASON_UNKNOWN = "TRADING_PERMISSION_UNKNOWN"
PERMISSION_REASON_DENIED = "TRADING_PERMISSION_DENIED"
PERMISSION_REASON_INSUFFICIENT = "TRADING_PERMISSION_INSUFFICIENT"
PERMISSION_REASON_EVIDENCE_MISSING = "TRADING_PERMISSION_EVIDENCE_MISSING"
PERMISSION_REASON_EVIDENCE_INCONSISTENT = "TRADING_PERMISSION_EVIDENCE_INCONSISTENT"
PERMISSION_REASON_SOURCE_UNTRUSTED = "TRADING_PERMISSION_SOURCE_UNTRUSTED"
PERMISSION_REASON_TIMESTAMP_MISSING = "TRADING_PERMISSION_TIMESTAMP_MISSING"
PERMISSION_REASON_STALE = "TRADING_PERMISSION_EVIDENCE_STALE"
PERMISSION_REASON_EXPIRED = "TRADING_PERMISSION_EVIDENCE_EXPIRED"
PERMISSION_REASON_ACCOUNT_MISMATCH = "TRADING_PERMISSION_ACCOUNT_MISMATCH"
PERMISSION_REASON_VENUE_MISMATCH = "TRADING_PERMISSION_VENUE_MISMATCH"
PERMISSION_REASON_CREDENTIAL_MISMATCH = "TRADING_PERMISSION_CREDENTIAL_MISMATCH"

DEFAULT_TRADING_PERMISSION_MAX_AGE_SECONDS = 300.0

_VERIFIED_PERMISSIONS = frozenset({
    PERMISSION_READ_ONLY,
    PERMISSION_TRADE,
    PERMISSION_WITHDRAW,
    PERMISSION_TRADE_AND_WITHDRAW,
})

_TRADING_PERMISSIONS = frozenset({
    PERMISSION_TRADE,
    PERMISSION_TRADE_AND_WITHDRAW,
})

_UNTRUSTED_SOURCES = frozenset({
    "",
    "NOT_VERIFIED",
    "UNVERIFIED",
    "NONE",
    "UNKNOWN",
})


def _normalize_permission(value):
    normalized = str(value or "").strip().upper()
    if normalized in _VERIFIED_PERMISSIONS:
        return normalized
    if normalized in {"READONLY", "READ-ONLY", "READ_ONLY_KEY"}:
        return PERMISSION_READ_ONLY
    if normalized in {"DENIED", "DENY"}:
        return PERMISSION_DENIED
    return PERMISSION_UNKNOWN


def _epoch_seconds(value):
    """Normalize epoch seconds / milliseconds / ISO text / datetime input."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:
            number /= 1000.0
        return number
    if hasattr(value, "timestamp"):
        try:
            return float(value.timestamp())
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        from datetime import datetime

        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def project_permission_contract(
    *,
    claimed_permission=None,
    verified_permission=None,
    verification_source=None,
    verified_at=None,
    credential_fingerprint=None,
    authenticated=None,
    venue=None,
    account_id=None,
    expires_at=None,
):
    """Separate a claimed key permission from a proven one.

    A hard-coded or self-declared ``READ_ONLY`` value is a claim, not proof.
    Only a non-empty authoritative ``verification_source`` plus a recognized
    ``verified_permission`` may set ``permissionStatus=VERIFIED``.  Venue,
    account and expiry are carried so a caller can refuse to reuse evidence
    that is not bound to the current runtime.
    """

    claimed = _normalize_permission(claimed_permission)
    verified_value = _normalize_permission(verified_permission)
    source = str(verification_source or "").strip()
    source_is_authoritative = source.upper() not in _UNTRUSTED_SOURCES
    verified = (
        verified_value in _VERIFIED_PERMISSIONS
        and source_is_authoritative
    )

    if verified:
        status = PERMISSION_STATUS_VERIFIED
    elif verified_value == PERMISSION_DENIED:
        status = PERMISSION_STATUS_DENIED
    elif authenticated is True:
        status = PERMISSION_STATUS_UNVERIFIED
    else:
        status = PERMISSION_STATUS_UNKNOWN

    private_read_ready = bool(authenticated is True and verified)
    trading_permission = (
        verified_value
        if verified and verified_value in _TRADING_PERMISSIONS
        else (
            "NONE"
            if verified
            else PERMISSION_UNKNOWN
        )
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "claimedPermission": claimed,
        "verifiedPermission": verified_value if verified else None,
        "permissionStatus": status,
        "verificationSource": source or "NOT_VERIFIED",
        "verifiedAt": verified_at,
        "expiresAt": expires_at,
        "venue": (str(venue).strip() or None) if venue is not None else None,
        "accountId": (
            str(account_id).strip() or None
        ) if account_id is not None else None,
        "credentialFingerprint": credential_fingerprint,
        "secretDisclosed": False,
        "privateReadReady": private_read_ready,
        "tradingPermission": trading_permission,
        "readSuccessImpliesNoTradingPermission": False,
    }


def evaluate_trading_permission_authority(
    contract,
    *,
    expected_venue=None,
    expected_account_id=None,
    expected_credential_fingerprint=None,
    now=None,
    max_age_seconds=DEFAULT_TRADING_PERMISSION_MAX_AGE_SECONDS,
):
    """Fail-closed trading-permission gate for REAL order entry.

    A ``VERIFIED`` string alone is never enough.  Evidence must carry a
    recognized TRADE permission, an authoritative source, a timestamp that is
    neither stale nor expired, and bindings that match the current venue /
    account / credential when those expectations are supplied.
    """

    import time as _time

    if not isinstance(contract, Mapping) or not contract:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "allowed": False,
            "reason": PERMISSION_REASON_EVIDENCE_MISSING,
            "reasons": [PERMISSION_REASON_EVIDENCE_MISSING],
            "permissionStatus": PERMISSION_STATUS_UNKNOWN,
            "tradingPermission": PERMISSION_UNKNOWN,
            "evaluatedAt": _time.time(),
            "checks": {},
            "contract": {},
        }

    normalized = dict(contract)
    checks = {}
    reasons = []

    status = str(
        normalized.get("permissionStatus") or ""
    ).strip().upper()
    verified_permission = _normalize_permission(
        normalized.get("verifiedPermission")
    )
    source = str(normalized.get("verificationSource") or "").strip()
    source_authoritative = source.upper() not in _UNTRUSTED_SOURCES

    checks["statusVerified"] = status == PERMISSION_STATUS_VERIFIED
    if status == PERMISSION_STATUS_DENIED:
        reasons.append(PERMISSION_REASON_DENIED)
    elif status == PERMISSION_STATUS_UNKNOWN or not status:
        reasons.append(PERMISSION_REASON_UNKNOWN)
    elif status != PERMISSION_STATUS_VERIFIED:
        reasons.append(PERMISSION_REASON_UNVERIFIED)

    checks["tradingPermission"] = (
        verified_permission in _TRADING_PERMISSIONS
    )
    if not checks["tradingPermission"]:
        if status == PERMISSION_STATUS_VERIFIED:
            reasons.append(PERMISSION_REASON_EVIDENCE_INCONSISTENT)
        else:
            reasons.append(PERMISSION_REASON_INSUFFICIENT)

    checks["sourceAuthoritative"] = source_authoritative
    if not source_authoritative:
        reasons.append(PERMISSION_REASON_SOURCE_UNTRUSTED)

    checked_at = _epoch_seconds(now)
    if checked_at is None:
        checked_at = _time.time()
    verified_at = _epoch_seconds(normalized.get("verifiedAt"))
    expires_at = _epoch_seconds(normalized.get("expiresAt"))

    checks["verifiedAtPresent"] = verified_at is not None
    if verified_at is None:
        reasons.append(PERMISSION_REASON_TIMESTAMP_MISSING)
    else:
        age = checked_at - verified_at
        if age < -60:
            reasons.append(PERMISSION_REASON_EVIDENCE_INCONSISTENT)
            checks["notFuture"] = False
        else:
            checks["notFuture"] = True
            if (
                max_age_seconds is not None
                and age > float(max_age_seconds)
            ):
                reasons.append(PERMISSION_REASON_STALE)

    checks["notExpired"] = True
    if expires_at is not None and checked_at >= expires_at:
        checks["notExpired"] = False
        reasons.append(PERMISSION_REASON_EXPIRED)

    evidence_fingerprint = normalized.get("credentialFingerprint")
    checks["credentialBound"] = True
    if expected_credential_fingerprint is not None:
        checks["credentialBound"] = bool(
            evidence_fingerprint
            and str(evidence_fingerprint)
            == str(expected_credential_fingerprint)
        )
        if not checks["credentialBound"]:
            reasons.append(PERMISSION_REASON_CREDENTIAL_MISMATCH)
    elif not evidence_fingerprint:
        checks["credentialBound"] = False
        reasons.append(PERMISSION_REASON_CREDENTIAL_MISMATCH)

    evidence_venue = normalized.get("venue")
    checks["venueBound"] = True
    if expected_venue is not None:
        checks["venueBound"] = bool(
            evidence_venue
            and str(evidence_venue).strip().upper()
            == str(expected_venue).strip().upper()
        )
        if not checks["venueBound"]:
            reasons.append(PERMISSION_REASON_VENUE_MISMATCH)

    evidence_account = normalized.get("accountId")
    checks["accountBound"] = True
    if expected_account_id is not None:
        checks["accountBound"] = bool(
            evidence_account
            and str(evidence_account) == str(expected_account_id)
        )
        if not checks["accountBound"]:
            reasons.append(PERMISSION_REASON_ACCOUNT_MISMATCH)

    reasons = list(dict.fromkeys(reasons))
    allowed = not reasons

    return {
        "schemaVersion": SCHEMA_VERSION,
        "allowed": allowed,
        "reason": (
            PERMISSION_AUTHORITY_VERIFIED if allowed else reasons[0]
        ),
        "reasons": reasons,
        "permissionStatus": status or PERMISSION_STATUS_UNKNOWN,
        "tradingPermission": (
            verified_permission
            if verified_permission in _TRADING_PERMISSIONS
            else normalized.get("tradingPermission") or PERMISSION_UNKNOWN
        ),
        "evaluatedAt": checked_at,
        "checks": checks,
        "contract": normalized,
    }


# ---------------------------------------------------------------------------
# Exchange client readiness
# ---------------------------------------------------------------------------


def project_exchange_client_readiness(
    *,
    client_constructed,
    credentials_present,
    public_read_ok,
    authenticated,
    permission_contract=None,
    real_order_allowed=False,
):
    """Keep public READ, private READ, trading client, and authority separate."""

    contract = (
        permission_contract
        if isinstance(permission_contract, Mapping)
        else {}
    )
    permission_verified = (
        contract.get("permissionStatus") == PERMISSION_STATUS_VERIFIED
    )

    public_read_ready = bool(
        client_constructed and credentials_present and public_read_ok
    )
    private_read_ready = bool(
        client_constructed
        and credentials_present
        and authenticated is True
        and permission_verified
    )
    # A private READ-capable client is still not an authority to trade.
    trading_client_ready = bool(private_read_ready)
    real_order_authority = bool(real_order_allowed)

    reasons = []
    if not client_constructed:
        reasons.append("EXCHANGE_CLIENT_NOT_CONSTRUCTED")
    if not credentials_present:
        reasons.append("KUCOIN_CREDENTIALS_MISSING")
    if not public_read_ready:
        reasons.append("PUBLIC_READ_NOT_READY")
    if not private_read_ready:
        reasons.append("PRIVATE_READ_NOT_READY")
    if not real_order_authority:
        reasons.append("REAL_ORDER_AUTHORITY_DISABLED")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "clientConstructed": bool(client_constructed),
        "credentialsPresent": bool(credentials_present),
        "publicReadReady": public_read_ready,
        "privateReadReady": private_read_ready,
        "tradingClientReady": trading_client_ready,
        "realOrderAuthority": real_order_authority,
        "permission": dict(contract),
        "reasonCodes": list(dict.fromkeys(reasons)),
        "publicReadImpliesPrivateRead": False,
        "privateReadImpliesTradingAuthority": False,
    }
