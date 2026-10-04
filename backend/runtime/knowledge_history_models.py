"""Shared read-only knowledge/history query contracts (WORK I②).

This module defines the *contract vocabulary* shared by the AI Advisor and AI
Supervisor read-only consumers.  It reads and writes nothing, has no authority,
and never invents a value.

The shared query layer it describes is READ-ONLY: it exposes already-written
canonical evidence (cycle evidence, trading trace, link projections) through one
bounded query service.  It never writes, never re-runs a producer/detector and
never calls an LLM/provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


CURSOR_VERSION = 1
DEFAULT_QUERY_LIMIT = 50
MAX_QUERY_LIMIT = 200

# An explicit, overridable freshness policy source label.  Thresholds are never
# hard-coded into the evaluation logic; this default is named so a caller can
# always tell where the threshold came from.
DEFAULT_FRESHNESS_POLICY_SOURCE = "DEFAULT_KNOWLEDGE_HISTORY_FRESHNESS_POLICY"
DEFAULT_MAX_AGE_SECONDS = 3600.0


class KnowledgeHistoryError(Exception):
    """Base class for shared knowledge/history query errors."""


class KnowledgeHistoryQueryError(KnowledgeHistoryError):
    """A structured, consumer-facing query validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class KnowledgeHistoryCursorError(KnowledgeHistoryQueryError):
    """A cursor is malformed, for a different query, or no longer valid."""


class KnowledgeHistorySecretError(KnowledgeHistoryQueryError):
    """A query or record carries secret-like material that must be rejected."""


class KnowledgeSource(str, Enum):
    """The physical read-only sources the shared layer can query."""

    CYCLE_EVIDENCE = "CYCLE_EVIDENCE"
    TRADING_TRACE = "TRADING_TRACE"


class FreshnessState(str, Enum):
    """Per-source freshness state (never used to discard history)."""

    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SourceAvailability(str, Enum):
    """Per-source availability in a query result."""

    AVAILABLE = "AVAILABLE"
    EMPTY = "EMPTY"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    UNSUPPORTED_FILTER = "UNSUPPORTED_FILTER"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class ConsumerKind(str, Enum):
    """Read-only consumers that share one query service."""

    AI_ADVISOR = "AI_ADVISOR"
    AI_SUPERVISOR = "AI_SUPERVISOR"


# The complete set of optional query filters.  A source declares which of these
# it can evaluate; a requested filter outside a source's capability excludes
# that source from the query instead of being silently ignored.
QUERY_FILTER_FIELDS: Tuple[str, ...] = (
    "cycle_id",
    "trace_id",
    "evidence_id",
    "stage",
    "stage_name",
    "symbol",
    "mode",
    "time_range",
    "status",
    "evidence_type",
    "availability",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> Optional[float]:
    """Return epoch seconds for an ISO-8601 string or an epoch number.

    Returns ``None`` when the value is absent or cannot be parsed; a caller
    must treat ``None`` as "unknown", never as "now".
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass(frozen=True)
class KnowledgeHistoryQuery:
    """One read-only, optionally-filtered knowledge/history query.

    Every field is optional and combinable.  ``source`` selects which physical
    sources are queried (all by default).  ``limit`` is clamped to
    :data:`MAX_QUERY_LIMIT`; ``cursor`` is opaque and validated by the service.
    """

    cycle_id: Optional[str] = None
    trace_id: Optional[str] = None
    evidence_id: Optional[str] = None
    stage: Optional[int] = None
    stage_name: Optional[str] = None
    symbol: Optional[str] = None
    mode: Optional[str] = None
    time_from: Optional[Any] = None
    time_to: Optional[Any] = None
    status: Optional[str] = None
    evidence_type: Optional[str] = None
    source: Optional[Tuple[str, ...]] = None
    availability: Optional[Tuple[str, ...]] = None
    limit: Optional[int] = None
    cursor: Optional[str] = None

    def requested_filters(self) -> dict:
        """Return only the filters the caller actually supplied."""

        requested: dict[str, Any] = {}
        if self.cycle_id is not None:
            requested["cycle_id"] = self.cycle_id
        if self.trace_id is not None:
            requested["trace_id"] = self.trace_id
        if self.evidence_id is not None:
            requested["evidence_id"] = self.evidence_id
        if self.stage is not None or self.stage_name is not None:
            requested["stage"] = self.stage if self.stage is not None else self.stage_name
        if self.stage_name is not None:
            requested["stage_name"] = self.stage_name
        if self.symbol is not None:
            requested["symbol"] = self.symbol
        if self.mode is not None:
            requested["mode"] = self.mode
        if self.time_from is not None or self.time_to is not None:
            requested["time_range"] = {"from": self.time_from, "to": self.time_to}
        if self.status is not None:
            requested["status"] = self.status
        if self.evidence_type is not None:
            requested["evidence_type"] = self.evidence_type
        if self.availability:
            requested["availability"] = tuple(self.availability)
        return requested

    def fingerprint_value(self) -> dict:
        """Return the stable value used for the opaque pagination cursor.

        ``limit`` and ``cursor`` are intentionally excluded so a caller may
        change the page size mid-pagination without invalidating the cursor.
        """

        return {
            "cycle_id": self.cycle_id,
            "trace_id": self.trace_id,
            "evidence_id": self.evidence_id,
            "stage": self.stage,
            "stage_name": self.stage_name,
            "symbol": self.symbol,
            "mode": self.mode,
            "time_from": self.time_from,
            "time_to": self.time_to,
            "status": self.status,
            "evidence_type": self.evidence_type,
            "source": tuple(self.source) if self.source else None,
            "availability": tuple(self.availability) if self.availability else None,
        }

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "trace_id": self.trace_id,
            "evidence_id": self.evidence_id,
            "stage": self.stage,
            "stage_name": self.stage_name,
            "symbol": self.symbol,
            "mode": self.mode,
            "time_from": self.time_from,
            "time_to": self.time_to,
            "status": self.status,
            "evidence_type": self.evidence_type,
            "source": list(self.source) if self.source else None,
            "availability": list(self.availability) if self.availability else None,
            "limit": self.limit,
            "cursor": self.cursor,
        }


@dataclass(frozen=True)
class FreshnessPolicy:
    """Configurable freshness thresholds, never hard-coded into evaluation.

    ``DEFAULT`` is explicit rather than implicit: one hour for both sources, and
    the ``policy_source`` label is returned in every freshness record so a
    consumer can always tell which threshold was applied.
    """

    max_age_by_source: Mapping[str, float] = field(
        default_factory=lambda: {
            KnowledgeSource.CYCLE_EVIDENCE.value: DEFAULT_MAX_AGE_SECONDS,
            KnowledgeSource.TRADING_TRACE.value: DEFAULT_MAX_AGE_SECONDS,
        }
    )
    policy_source: str = DEFAULT_FRESHNESS_POLICY_SOURCE

    def threshold_for(self, source: str) -> Optional[float]:
        value = self.max_age_by_source.get(source)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def evaluate(
        self,
        *,
        source: str,
        observed_at: Any,
        now: datetime,
        source_revision: Optional[str] = None,
        reason_unavailable: Optional[str] = None,
    ) -> dict:
        """Evaluate freshness for one source; STALE history is still returned."""

        threshold = self.threshold_for(source)
        observed_seconds = parse_timestamp(observed_at)
        record: dict[str, Any] = {
            "source": source,
            "observed_at": observed_at,
            "observed_at_seconds": observed_seconds,
            "source_revision": source_revision,
            "state": None,
            "reason": None,
            "age_seconds": None,
            "max_age_seconds": threshold,
            "threshold_source": self.policy_source,
        }
        if reason_unavailable is not None:
            record["state"] = FreshnessState.UNKNOWN.value
            record["reason"] = reason_unavailable
            return record
        if observed_seconds is None or threshold is None:
            record["state"] = FreshnessState.UNKNOWN.value
            record["reason"] = "SOURCE_OBSERVED_AT_UNKNOWN"
            return record
        age = now.timestamp() - observed_seconds
        if age < 0:
            age = 0.0
        record["age_seconds"] = age
        if age <= threshold:
            record["state"] = FreshnessState.FRESH.value
            record["reason"] = "WITHIN_MAX_AGE"
        else:
            record["state"] = FreshnessState.STALE.value
            record["reason"] = "AGE_EXCEEDS_MAX_AGE"
        return record
