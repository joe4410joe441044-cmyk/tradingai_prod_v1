"""Process-memory holder for completed Supervisor shadow evaluations.

The conversation service owns this holder. A read copies JSON-safe fields
under one lock. This module does not import the snapshot builder, the
runtime snapshot adapter, BotManager, the owner snapshot, or context code.
It does not evaluate, refresh an account, or place an order.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
import threading
from typing import Any, Mapping

SCHEMA_VERSION = 1
EVALUATION_KIND = "CONVERSATION_SHADOW"
SOURCE_OWNER = "SupervisorConversationService"
_SLOTS = ("master", "mm")
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|credential|private)"
)

_LOCK = threading.Lock()
_SLOT_VALUES: dict[str, dict[str, Any] | None] = {"master": None, "mm": None}
_REVISION = 0
_DIAGNOSTIC: dict[str, Any] = {"outcome": None, "error": None, "revision": 0}


def accept_completed(
    *,
    slot: str,
    status: str | None,
    failure_code: object,
    mode: str | None,
    state: str | None,
    recommendation: str | None,
    evaluation_id: str | None,
    completed_at: datetime | None,
) -> dict[str, Any]:
    """Store one completed slot. Failures, older results, and exceptions do not.

    A clock that is missing or naive is stored as ``evaluationCompletedAt=null``.
    That outcome stays visible as ``STORED_CLOCK_UNKNOWN``.
    """

    try:
        _accept(
            slot=slot,
            status=status,
            failure_code=failure_code,
            mode=mode,
            state=state,
            recommendation=recommendation,
            evaluation_id=evaluation_id,
            completed_at=completed_at,
        )
    except Exception as exc:
        note_write_failure(exc)
    return read_diagnostic()


def note_write_failure(exc: BaseException) -> None:
    """Record a write failure without replacing a stored slot."""

    with _LOCK:
        _remember_locked("WRITE_FAILED", type(exc).__name__)


def read_diagnostic() -> dict[str, Any]:
    """Return a copy of the latest write outcome."""

    with _LOCK:
        return {
            "outcome": _DIAGNOSTIC.get("outcome"),
            "error": _DIAGNOSTIC.get("error"),
            "revision": _DIAGNOSTIC.get("revision"),
        }


def read_holder() -> dict[str, Any]:
    """Return a JSON-safe copy. The caller cannot mutate the holder."""

    with _LOCK:
        master = _copy_slot(_SLOT_VALUES["master"])
        mm = _copy_slot(_SLOT_VALUES["mm"])
        revision = _REVISION
    return _combined(master, mm, revision)


def publication_fragment() -> dict[str, Any] | None:
    """Allowlisted supervisor fragment. Missing holder data returns None.

    ``supervisorState`` is omitted because the completed result has no such
    field. The completion clock is copied as ``producerObservedAt`` and
    ``lastEvaluation``. No freshness policy is attached.
    """

    holder = read_holder()
    if holder.get("masterSlot") is None and holder.get("mmSlot") is None:
        return None
    fragment: dict[str, Any] = {"revision": holder["revision"]}
    for name in (
        "masterState",
        "mmState",
        "shadowState",
        "lastEvaluation",
        "currentRecommendation",
    ):
        if name in holder:
            fragment[name] = holder[name]
    fragment["producerObservedAt"] = holder.get("evaluationCompletedAt")
    return fragment


def reset_holder() -> None:
    """Drop process memory. Tests use this so one case cannot leak into another."""

    global _REVISION
    with _LOCK:
        _SLOT_VALUES["master"] = None
        _SLOT_VALUES["mm"] = None
        _REVISION = 0
        _DIAGNOSTIC["outcome"] = None
        _DIAGNOSTIC["error"] = None
        _DIAGNOSTIC["revision"] = 0


def _accept(
    *,
    slot: str,
    status: str | None,
    failure_code: object,
    mode: str | None,
    state: str | None,
    recommendation: str | None,
    evaluation_id: str | None,
    completed_at: datetime | None,
) -> None:
    if slot not in _SLOTS:
        _reject("REJECTED_INCOMPLETE")
        return
    if failure_code is not None or status == "FAILED_CLOSED":
        _reject("REJECTED_FAILED")
        return
    if status != "COMPLETED":
        _reject("REJECTED_INCOMPLETE")
        return
    safe_state = _safe_token(state)
    if safe_state is None:
        _reject("REJECTED_INCOMPLETE")
        return
    stamp = _completion_stamp(completed_at)
    body: dict[str, Any] = {
        "evaluationId": _safe_event_id(evaluation_id),
        "evaluationCompletedAt": stamp,
        "evaluationKind": EVALUATION_KIND,
        "sourceOwner": SOURCE_OWNER,
        "shadowState": _safe_token(mode),
    }
    if slot == "mm":
        body["mmState"] = safe_state
    else:
        body["masterState"] = safe_state
        safe_recommendation = _safe_token(recommendation)
        if safe_recommendation is not None:
            body["currentRecommendation"] = safe_recommendation
    _commit_locked(slot, body, stamp)


def _commit_locked(slot: str, body: Mapping[str, Any], stamp: str | None) -> None:
    global _REVISION
    stored = {key: value for key, value in body.items()}
    with _LOCK:
        current = _SLOT_VALUES[slot]
        if current is not None and not _strictly_newer(
            stamp, current.get("evaluationCompletedAt")
        ):
            _remember_locked("REJECTED_NOT_NEWER", None)
            return
        _SLOT_VALUES[slot] = stored
        _REVISION += 1
        outcome = "STORED_CLOCK_UNKNOWN" if stamp is None else "STORED"
        _remember_locked(outcome, None)


def _reject(outcome: str) -> None:
    with _LOCK:
        _remember_locked(outcome, None)


def _remember_locked(outcome: str, error: str | None) -> None:
    _DIAGNOSTIC["outcome"] = outcome
    _DIAGNOSTIC["error"] = error
    _DIAGNOSTIC["revision"] = _REVISION


def _combined(
    master: dict[str, Any] | None,
    mm: dict[str, Any] | None,
    revision: int,
) -> dict[str, Any]:
    newer = _newer_slot(master, mm)
    completed_at = None if newer is None else newer.get("evaluationCompletedAt")
    shadow = None if newer is None else newer.get("shadowState")
    if shadow is None:
        for slot in (master, mm):
            if slot is not None and slot.get("shadowState") is not None:
                shadow = slot.get("shadowState")
                break
    holder: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "evaluationKind": EVALUATION_KIND,
        "sourceOwner": SOURCE_OWNER,
        "revision": revision,
        "masterSlot": master,
        "mmSlot": mm,
        "evaluationCompletedAt": completed_at,
        "lastEvaluation": completed_at,
        "shadowState": shadow,
    }
    if mm is not None and "mmState" in mm:
        holder["mmState"] = mm["mmState"]
    if master is not None and "masterState" in master:
        holder["masterState"] = master["masterState"]
    if master is not None and "currentRecommendation" in master:
        holder["currentRecommendation"] = master["currentRecommendation"]
    return holder


def _newer_slot(
    master: dict[str, Any] | None,
    mm: dict[str, Any] | None,
) -> dict[str, Any] | None:
    ranked: list[tuple[datetime, dict[str, Any]]] = []
    for slot in (master, mm):
        if slot is None:
            continue
        parsed = _parse_stamp(slot.get("evaluationCompletedAt"))
        if parsed is not None:
            ranked.append((parsed, slot))
    if not ranked:
        for slot in (master, mm):
            if slot is not None:
                return slot
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[-1][1]


def _strictly_newer(new_stamp: str | None, old_stamp: object) -> bool:
    new_parsed = _parse_stamp(new_stamp)
    if new_parsed is None:
        return False
    old_parsed = _parse_stamp(old_stamp if isinstance(old_stamp, str) else None)
    if old_parsed is None:
        return True
    return new_parsed > old_parsed


def _completion_stamp(value: datetime | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_token(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    if _TOKEN.fullmatch(value) is None or _SECRET.search(value):
        return None
    return value


def _safe_event_id(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    if _EVENT_ID.fullmatch(value) is None or _SECRET.search(value):
        return None
    return value


def _copy_slot(slot: dict[str, Any] | None) -> dict[str, Any] | None:
    if slot is None:
        return None
    return {key: value for key, value in slot.items()}
