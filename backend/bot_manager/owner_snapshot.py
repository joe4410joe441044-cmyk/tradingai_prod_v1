"""JSON publication document for an owner-published BotManager cache.

The functions in this module do not read a live runtime, take a runtime lock,
or talk to an exchange. Callers pass values they already hold.
``publishedAt`` is the time the owner stored the document. It is not a
producer observation time.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from backend.context.runtime_projection import parse_producer_time
from backend.context.snapshot_copy import copy_json_snapshot
from backend.context.injection_contract import SnapshotRejected

SCHEMA_VERSION = "tradingai-owner-snapshot/v1"
SOURCE = "bot_manager_publication"
OWNER = "BotManager"
NOT_PUBLISHED = "NOT_PUBLISHED"
PARTIAL = "PARTIAL"

_BLOCKED = (
    "real_account",
    "execution_control",
    "money_management",
    "supervisor",
)
_DOMAIN_FIELDS = {
    "execution_control": (
        "selectedMode",
        "tradeMode",
        "executionEnabled",
        "entryAllowed",
        "liveOrderAllowed",
        "realOrderAllowed",
        "emergencyStop",
        "pendingOrder",
        "positionGuard",
        "rootBlocker",
    ),
    "money_management": (
        "capital",
        "equity",
        "availableCapital",
        "riskState",
        "positionSize",
        "exposure",
        "drawdown",
        "recoveryState",
        "revision",
        "mmObservationCompletedAt",
        "inputCompleteness",
        "inputScope",
        "evidenceRevision",
        "mmInvalidationReason",
        "producerLifecycle",
        "producerLifecycleChangedAt",
        "liveBalanceSource",
        "livePositionSource",
        "liveAuthenticated",
        "liveStale",
        "liveSourceObservedAt",
        "liveSnapshotGeneration",
    ),
    "real_account": (
        "connectionState",
        "authenticationState",
        "accountType",
        "syncState",
        "lastSync",
        "permissionState",
        "liveExecutionAvailability",
    ),
    "supervisor": (
        "supervisorState",
        "masterState",
        "mmState",
        "shadowState",
        "lastEvaluation",
        "currentRecommendation",
        "revision",
    ),
    "market_selection": (
        "activeSymbol",
        "selectionMode",
        "manualSelection",
        "autoSelection",
        "selectionAuthority",
        "revision",
    ),
    "market_intelligence": (
        "activeMarket",
        "marketDataFreshness",
        "microstructureState",
        "decisionState",
    ),
}
_PRODUCER_LIFECYCLE = {"STARTING", "RUNNING", "STOPPING", "STOPPED"}
_MM_INVALIDATION_REASONS = {
    "PAPER_INPUT_MUTATION",
    "PAPER_MANUAL_ENTRY",
    "PAPER_MANUAL_CLOSE",
    "PAPER_EMERGENCY_FLATTEN",
    "PAPER_CAPITAL_RESET",
    "PAPER_RUNTIME_STOP",
    "LIVE_MANUAL_CLOSE",
    "LIVE_RUNTIME_STOP",
    "LIVE_ACCOUNT_CACHE_MUTATION",
    "LIVE_SOURCE_CHANGED",
    "LIVE_AUTHENTICATION_CHANGED",
    "LIVE_CACHE_STALE",
}
_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|credential|cookie|session|account[_-]?id|private)"
)
_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+|previous\s+|prior\s+)*instructions|"
    r"system\s+prompt|you\s+are\s+now|do\s+not\s+follow|"
    r"disregard\s+(all\s+|any\s+|previous\s+)*instructions)"
)


def unavailable_owner_snapshot() -> dict[str, Any]:
    """Initial document. It does not guess a mode, a side, or a loop state."""

    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": SOURCE,
        "owner": OWNER,
        "availability": "UNAVAILABLE",
        "publishedAt": None,
        "observedAt": None,
        "producerObservedAt": None,
        "revision": 0,
        "errorState": NOT_PUBLISHED,
        "unavailable": list(_BLOCKED),
        "payload": {},
    }


def _accept(value: Any) -> tuple[Any, str | None]:
    try:
        return copy_json_snapshot(value), None
    except SnapshotRejected:
        return None, "REJECTED"


def merge_owner_snapshot(
    previous: dict[str, Any] | None,
    *,
    paper_account: Any = None,
    runtime_result: Any = None,
    update_paper: bool = False,
    update_runtime: bool = False,
    published_at: str | None = None,
    runtime_domains: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a new document. ``previous`` is not modified.

    A fragment that fails the JSON copy keeps the previous accepted fragment.
    ``published_at`` is stored separately from producer clocks.
    """

    current = previous if isinstance(previous, dict) else unavailable_owner_snapshot()
    payload = dict(current.get("payload") or {})
    rejected = False
    changed = False

    if update_paper:
        copied, failure = _accept(paper_account)
        if failure is None and isinstance(copied, dict):
            payload["position_account"] = copied
            payload["position_mode"] = "PAPER"
            changed = True
        else:
            rejected = True

    if update_runtime:
        copied, failure = _accept(runtime_result)
        if failure is None and isinstance(copied, dict):
            payload["trading_cycle_runtime_result"] = copied
            changed = True
        else:
            rejected = True

    unavailable = [
        name
        for name in (current.get("unavailable") or list(_BLOCKED))
        if isinstance(name, str)
    ]
    if isinstance(runtime_domains, Mapping):
        for key, value in runtime_domains.items():
            if key not in _DOMAIN_FIELDS or value is None:
                continue
            fragment = _domain_fragment(key, value)
            if fragment is None:
                rejected = True
                continue
            payload[key] = fragment
            unavailable = [name for name in unavailable if name != key]
            changed = True

    if not changed:
        if not rejected:
            return current
        ready = _ready(payload)
        try:
            revision = int(current.get("revision") or 0) + 1
        except (TypeError, ValueError):
            revision = 1
        return {
            "schemaVersion": SCHEMA_VERSION,
            "source": SOURCE,
            "owner": OWNER,
            "availability": "READY" if ready else "UNAVAILABLE",
            "publishedAt": published_at,
            "observedAt": None,
            "producerObservedAt": None,
            "revision": revision,
            "errorState": PARTIAL,
            "unavailable": unavailable,
            "payload": payload,
        }

    ready = _ready(payload)
    try:
        revision = int(current.get("revision") or 0) + 1
    except (TypeError, ValueError):
        revision = 1
    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": SOURCE,
        "owner": OWNER,
        "availability": "READY" if ready else "UNAVAILABLE",
        "publishedAt": published_at,
        "observedAt": None,
        "producerObservedAt": None,
        "revision": revision,
        "errorState": PARTIAL if rejected else None,
        "unavailable": unavailable,
        "payload": payload,
    }


def _ready(payload: Mapping[str, Any]) -> bool:
    return any(key in payload for key in ("position_account", "trading_cycle_runtime_result")) or any(
        key in payload for key in _DOMAIN_FIELDS
    )


def _domain_fragment(key: str, value: Any) -> dict[str, Any] | None:
    """Copy an already-held domain. Missing clocks stay missing."""

    if not isinstance(value, Mapping):
        return None
    candidate = {
        name: value[name]
        for name in _DOMAIN_FIELDS[key]
        if name in value
    }
    for name in (
        "producerObservedAt",
        "freshness",
        "freshnessPolicy",
        "stale",
        "lastSync",
        "connected",
        "authenticated",
        "permission",
    ):
        if name in value:
            candidate[name] = value[name]
    copied, failure = _accept(candidate)
    if failure is not None or not isinstance(copied, dict):
        return None
    selected: dict[str, Any] = {}
    for name in _DOMAIN_FIELDS[key]:
        if name not in copied or _SECRET_KEY.search(name):
            continue
        item = _public_value(copied[name])
        if item is _DROP:
            continue
        selected[name] = item
    if key == "real_account":
        _alias_live_account(copied, selected)
    observed = copied.get("producerObservedAt")
    if observed is None and key == "real_account":
        observed = copied.get("lastSync")
    parsed = parse_producer_time(observed)
    selected["producerObservedAt"] = (
        None if parsed is None else parsed.isoformat().replace("+00:00", "Z")
    )
    freshness = copied.get("freshness")
    if freshness in {"STALE", "UNKNOWN", "HISTORICAL", "FRESH"}:
        selected["freshness"] = freshness
    elif copied.get("stale") is True:
        selected["freshness"] = "STALE"
    else:
        selected["freshness"] = "UNKNOWN"
    policy = _freshness_policy(key, copied.get("freshnessPolicy"))
    if policy is not None:
        selected["freshnessPolicy"] = policy
    if key == "execution_control":
        selected["orderEffect"] = "NONE"
    if not any(name in selected for name in _DOMAIN_FIELDS[key]):
        return None
    return selected


def _alias_live_account(copied: Mapping[str, Any], selected: dict[str, Any]) -> None:
    mapping = {
        "connected": "connectionState",
        "authenticated": "authenticationState",
        "permission": "permissionState",
    }
    for source, target in mapping.items():
        if target in selected or source not in copied:
            continue
        item = _public_value(copied[source])
        if item is _DROP:
            continue
        selected[target] = item


def _freshness_policy(key: str, value: Any) -> dict[str, Any] | None:
    if key != "money_management" or not isinstance(value, dict):
        return None
    if value.get("source") != "moneyManagement":
        return None
    maximum = value.get("maximumAgeSeconds")
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
        return None
    if not math.isfinite(float(maximum)) or float(maximum) < 0:
        return None
    tolerance = value.get("futureToleranceSeconds", 0)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        return None
    if not math.isfinite(float(tolerance)) or float(tolerance) < 0:
        return None
    return {
        "source": "moneyManagement",
        "maximumAgeSeconds": float(maximum),
        "futureToleranceSeconds": float(tolerance),
    }


_DROP = object()


def _public_value(value: Any) -> Any:
    if isinstance(value, str):
        if _SECRET_KEY.search(value):
            return _DROP
        return _INJECTION.sub("[REMOVED:PROMPT_INJECTION]", value)
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                continue
            child = _public_value(item)
            if child is _DROP:
                continue
            cleaned[key] = child
        return cleaned
    if isinstance(value, list):
        return [item for item in (_public_value(item) for item in value) if item is not _DROP]
    return value


def held_runtime_domains(owner: Any) -> dict[str, Any] | None:
    """Project caches the owner already stores. This does not refresh them."""

    domains: dict[str, Any] = {}
    for key, fragment in (
        ("real_account", _held_live_account(owner)),
        ("money_management", _held_money_management(owner)),
        ("execution_control", _held_execution(owner)),
        ("market_selection", _held_market_selection(owner)),
        ("market_intelligence", _held_market_intelligence(owner)),
    ):
        if fragment:
            domains[key] = fragment
    supervisor = _held_supervisor_evaluation()
    if supervisor:
        domains["supervisor"] = supervisor
    return domains or None


def _held_supervisor_evaluation() -> dict[str, Any] | None:
    """Copy completed conversation slots. This does not run a supervisor."""

    from backend.supervisor.held_evaluation_cache import publication_fragment

    fragment = publication_fragment()
    if not isinstance(fragment, dict) or not fragment:
        return None
    return fragment


def _held_live_account(owner: Any) -> dict[str, Any] | None:
    raw = getattr(owner, "real_account_snapshot", None)
    if not isinstance(raw, dict):
        return None
    if parse_producer_time(raw.get("lastSync")) is None and parse_producer_time(
        raw.get("producerObservedAt")
    ) is None:
        return None
    names = (
        "connectionState",
        "authenticationState",
        "accountType",
        "syncState",
        "lastSync",
        "permissionState",
        "liveExecutionAvailability",
        "producerObservedAt",
        "connected",
        "authenticated",
        "permission",
        "stale",
        "freshness",
    )
    return {name: raw[name] for name in names if name in raw}


def _copy_mm_observation_completion(snap: Any, fragment: dict[str, Any]) -> None:
    """Copy the completion clock only when it still belongs to this revision."""

    completed = getattr(snap, "mm_observation_completed_at", None)
    evidence_revision = getattr(snap, "mm_observation_evidence_revision", None)
    revision = getattr(snap, "revision", None)
    scope = getattr(snap, "mm_observation_input_scope", None)
    completeness = getattr(snap, "mm_observation_input_completeness", None)
    stamp = _iso(completed)
    if (
        stamp is None
        or type(evidence_revision) is not int
        or type(revision) is not int
        or evidence_revision != revision
        or completeness != "COMPLETE"
        or scope not in {"PAPER_ENGINE_ACCOUNT", "LIVE_ACCOUNT_CACHE"}
    ):
        return
    fragment["mmObservationCompletedAt"] = stamp
    fragment["inputCompleteness"] = completeness
    fragment["inputScope"] = scope
    fragment["evidenceRevision"] = evidence_revision
    if scope == "LIVE_ACCOUNT_CACHE":
        _copy_live_source_evidence(snap, fragment)


def _held_money_management(owner: Any) -> dict[str, Any] | None:
    metrics = getattr(owner, "money_management_runtime_metrics", None)
    read = getattr(metrics, "snapshot", None)
    if not callable(read):
        return None
    try:
        snap = read()
    except Exception:
        return None
    if getattr(snap, "observation_valid", False) is not True:
        return None
    if getattr(snap, "source_state", "") == "NOT_INITIALIZED":
        return None
    observed = _iso(getattr(snap, "as_of", None))
    fragment = {
        "equity": _number(getattr(snap, "current_equity", None)),
        "availableCapital": _number(getattr(snap, "available_balance", None)),
        "exposure": _number(getattr(snap, "open_exposure", None)),
        "drawdown": _number(getattr(snap, "current_drawdown_pct", None)),
        "positionSize": getattr(snap, "position_count", None),
        "revision": getattr(snap, "revision", None),
    }
    if observed is not None:
        fragment["producerObservedAt"] = observed
    _copy_mm_observation_completion(snap, fragment)
    if "mmObservationCompletedAt" not in fragment:
        reason = getattr(snap, "mm_invalidation_reason", None)
        if reason in _MM_INVALIDATION_REASONS:
            fragment["mmInvalidationReason"] = reason
    lifecycle = getattr(owner, "lifecycle_state", None)
    if lifecycle in _PRODUCER_LIFECYCLE:
        fragment["producerLifecycle"] = lifecycle
    changed_at = _lifecycle_changed_at(owner)
    if changed_at is not None:
        fragment["producerLifecycleChangedAt"] = changed_at
    return fragment


def _copy_live_source_evidence(snap: Any, fragment: dict[str, Any]) -> None:
    """Copy LIVE attestation stored at the completion note. Do not invent it."""

    balance_source = getattr(snap, "live_balance_source", None)
    position_source = getattr(snap, "live_position_source", None)
    if isinstance(balance_source, str) and balance_source:
        fragment["liveBalanceSource"] = balance_source
    if isinstance(position_source, str) and position_source:
        fragment["livePositionSource"] = position_source
    authenticated = getattr(snap, "live_authenticated", None)
    if type(authenticated) is bool:
        fragment["liveAuthenticated"] = authenticated
    stale = getattr(snap, "live_stale", None)
    if type(stale) is bool:
        fragment["liveStale"] = stale
    observed = _iso(getattr(snap, "live_source_observed_at", None))
    if observed is not None:
        fragment["liveSourceObservedAt"] = observed
    generation = getattr(snap, "live_snapshot_generation", None)
    if type(generation) is int and generation >= 0:
        fragment["liveSnapshotGeneration"] = generation


def _lifecycle_changed_at(owner: Any) -> str | None:
    """Format the existing lifecycle transition clock. It is not a heartbeat."""

    value = getattr(owner, "lifecycle_changed_at", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or float(value) < 0:
        return None
    return (
        datetime.fromtimestamp(float(value), tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


_EXECUTION_CACHE_FIELDS = (
    "executionEnabled",
    "entryAllowed",
    "liveOrderAllowed",
    "realOrderAllowed",
    "positionGuard",
    "rootBlocker",
    "producerObservedAt",
)


def _held_execution(owner: Any) -> dict[str, Any] | None:
    fragment: dict[str, Any] = {}
    state = getattr(owner, "state", None)
    if state is not None and hasattr(state, "emergency_stop"):
        fragment["emergencyStop"] = state.emergency_stop
        if hasattr(state, "pending_order"):
            pending = state.pending_order
            if pending is None or isinstance(pending, (str, bool, int, float)):
                fragment["pendingOrder"] = pending
    cache = getattr(owner, "execution_authority_cache", None)
    if isinstance(cache, dict):
        for name in _EXECUTION_CACHE_FIELDS:
            if name not in cache:
                continue
            value = cache[name]
            if name == "producerObservedAt":
                observed = _iso(value)
                if observed is not None:
                    fragment[name] = observed
                continue
            if name == "rootBlocker" and isinstance(value, str):
                fragment[name] = value
                continue
            if type(value) is bool:
                fragment[name] = value
    return fragment or None


def _held_market_selection(owner: Any) -> dict[str, Any] | None:
    mode = getattr(owner, "selection_mode", None)
    if not isinstance(mode, str) or not mode.strip():
        return None
    symbol = getattr(owner, "_active_symbol", None)
    if symbol is not None and not isinstance(symbol, str):
        symbol = None
    fragment = {
        "activeSymbol": symbol,
        "selectionMode": mode.strip(),
        "manualSelection": mode.strip().upper() == "MANUAL",
        "autoSelection": mode.strip().upper() == "AUTO",
    }
    observed = _iso(getattr(owner, "selection_determined_at", None))
    if observed is not None:
        fragment["producerObservedAt"] = observed
    return fragment


def _held_market_intelligence(owner: Any) -> dict[str, Any] | None:
    raw = getattr(owner, "market_snapshot", None)
    if not isinstance(raw, dict):
        return None
    symbol = raw.get("exchangeSymbol")
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    fragment: dict[str, Any] = {
        "activeMarket": symbol.strip(),
        "marketDataFreshness": (
            raw.get("dataQuality")
            if isinstance(raw.get("dataQuality"), str)
            else "UNKNOWN"
        ),
    }
    observed = _iso(raw.get("timestamp"))
    if observed is not None:
        fragment["producerObservedAt"] = observed
    return fragment


def _iso(value: Any) -> str | None:
    parsed = parse_producer_time(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _number(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    return value
