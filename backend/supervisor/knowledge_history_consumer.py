"""READ-ONLY Supervisor consumer of the shared knowledge/history query layer.

The Supervisor is a SHADOW, observation-only authority: it never commands the
runtime and it has no scheduler.  This module connects it to the *same* shared
knowledge/history query foundation the AI Advisor uses
(:mod:`backend.runtime.knowledge_history_query`) so the two consumers never
build separate stores or duplicate source authority.

Guarantees:

* a dedicated, default-OFF feature flag
  (:data:`SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED_ENV`) gates the whole connection;
* importing or constructing the consumer performs no I/O and runs no query;
* queries are planned from *observation/evaluation inputs* (the read-only
  snapshot), never from Advisor questions or conversation state;
* the query is bounded, deterministic, uses the shared hard maximum and never
  accepts a caller cursor;
* the result is converted into a bounded, sanitized context block exposing
  provenance, freshness, availability, partial-result and unsupported-filter
  warnings plus an explicit uncertainty level;
* knowledge/history data is observational metadata only: it never changes an
  evaluation, never allows/blocks trading and never triggers remediation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Tuple

from backend.ai_advisor.knowledge_history_consumer import (
    assemble_knowledge_history_context,
)
from backend.runtime.cycle_evidence import EvidenceType, LIFECYCLE_STAGE_NAMES
from backend.runtime.knowledge_history_models import KnowledgeHistoryQuery
from backend.runtime.knowledge_history_query import (
    KnowledgeHistoryQueryFacade,
    shared_knowledge_history_facade,
)

SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED_ENV = "AI_SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED"

# Small request-time budget: observation history must never flood the snapshot.
SUPERVISOR_QUERY_DEFAULT_LIMIT = 6
SUPERVISOR_CONTEXT_MAX_ITEMS = 12
SUPERVISOR_CONTEXT_MAX_CHARACTERS = 12_000
SUPERVISOR_DEFAULT_TIME_WINDOW_SECONDS = 86_400.0

MAX_IDENTIFIER_CHARACTERS = 128

_TRUTHY = {"1", "true", "yes", "on"}
_STATUS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def supervisor_knowledge_history_enabled(
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return whether the Supervisor knowledge/history consumer is enabled.

    Default OFF.  Independent of ``AI_ADVISOR_KNOWLEDGE_HISTORY_ENABLED`` and of
    ``CYCLE_EVIDENCE_PHASE_A_ENABLED``.
    """

    env = os.environ if environ is None else environ
    raw = str(env.get(SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED_ENV, "")).strip().lower()
    return raw in _TRUTHY


@dataclass(frozen=True)
class SupervisorKnowledgeHistoryPlan:
    """A deterministic, read-only query plan derived from observation inputs."""

    relevant: bool
    reason: str
    query: Optional[KnowledgeHistoryQuery]
    notes: Tuple[str, ...] = ()
    scope: dict = field(default_factory=dict)


def _clean_text(value: Any, *, max_length: int = MAX_IDENTIFIER_CHARACTERS) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    return token[:max_length]


def _snapshot_inputs(snapshot: Any) -> dict:
    market = getattr(snapshot, "market", None)
    trade = getattr(snapshot, "trade", None)
    # ``status`` is never derived from the snapshot: the snapshot's decision
    # status and the evidence status vocabularies are not interchangeable, and
    # deriving it would silently over-narrow the query.  It is only applied when
    # an evaluation input supplies it explicitly.
    return {
        "cycle_id": _clean_text(getattr(market, "selectionCycleId", None)),
        "symbol": _clean_text(getattr(market, "activeSymbol", None)),
        "mode": _clean_text(getattr(trade, "selectedMode", None)),
    }


def _anomaly_domains(snapshot: Any) -> tuple[str, ...]:
    warnings = getattr(snapshot, "warnings", ()) or ()
    domains = {
        warning.domain
        for warning in warnings
        if isinstance(getattr(warning, "domain", None), str)
        and getattr(warning, "domain").strip()
    }
    return tuple(sorted(domains)[:32])


def _captured_at(snapshot: Any) -> Optional[datetime]:
    value = getattr(snapshot, "capturedAt", None)
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        return None
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def plan_supervisor_query(
    snapshot: Any,
    *,
    cycle_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    symbol: Optional[str] = None,
    stage: Optional[int] = None,
    mode: Optional[str] = None,
    status: Optional[str] = None,
    evidence_type: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    time_window_seconds: float = SUPERVISOR_DEFAULT_TIME_WINDOW_SECONDS,
) -> SupervisorKnowledgeHistoryPlan:
    """Build a bounded query plan from observation inputs only.

    Explicit ``cycle_id``/``trace_id``/``symbol``/... arguments are evaluation
    inputs supplied by the caller; nothing missing is inferred.
    """

    notes: list[str] = []
    derived = _snapshot_inputs(snapshot)

    resolved_cycle = _clean_text(cycle_id) or derived["cycle_id"]
    resolved_trace = _clean_text(trace_id)
    resolved_symbol = _clean_text(symbol) or derived["symbol"]

    resolved_mode = _clean_text(mode) or derived["mode"]
    if resolved_mode is not None:
        resolved_mode = resolved_mode.upper()
        if resolved_mode not in {"PAPER", "LIVE"}:
            notes.append("MODE_UNRECOGNIZED")
            resolved_mode = None

    resolved_status = _clean_text(status)
    if resolved_status is not None:
        resolved_status = resolved_status.upper()
        if not _STATUS_PATTERN.match(resolved_status):
            notes.append("STATUS_UNRECOGNIZED")
            resolved_status = None

    resolved_stage: Optional[int] = None
    if stage is not None:
        try:
            candidate_stage = int(stage)
        except (TypeError, ValueError):
            notes.append("STAGE_UNPARSEABLE")
        else:
            if candidate_stage in LIFECYCLE_STAGE_NAMES:
                resolved_stage = candidate_stage
            else:
                notes.append("STAGE_OUT_OF_RANGE")

    resolved_evidence_type: Optional[str] = None
    if evidence_type is not None:
        token = _clean_text(evidence_type)
        token = token.upper() if token else None
        if token in {item.value for item in EvidenceType}:
            resolved_evidence_type = token
        else:
            notes.append("EVIDENCE_TYPE_UNRECOGNIZED")

    resolved_time_from = time_from
    resolved_time_to = time_to
    captured = _captured_at(snapshot)
    if resolved_time_from is None and resolved_time_to is None and captured is not None:
        try:
            window = float(time_window_seconds)
        except (TypeError, ValueError):
            window = SUPERVISOR_DEFAULT_TIME_WINDOW_SECONDS
        if window < 0:
            window = SUPERVISOR_DEFAULT_TIME_WINDOW_SECONDS
        resolved_time_from = _iso(captured - timedelta(seconds=window))
        resolved_time_to = _iso(captured)

    anomaly_scope = _anomaly_domains(snapshot)
    scope = {
        "timeWindowSeconds": time_window_seconds,
        "snapshotCapturedAt": _iso(captured) if captured is not None else None,
        "anomalyDomains": list(anomaly_scope),
    }

    relevant = bool(resolved_cycle or resolved_trace or resolved_symbol)
    if not relevant:
        return SupervisorKnowledgeHistoryPlan(
            False,
            "NO_OBSERVATION_SCOPE",
            None,
            tuple(notes),
            scope,
        )

    query = KnowledgeHistoryQuery(
        cycle_id=resolved_cycle,
        trace_id=resolved_trace,
        evidence_id=None,
        stage=resolved_stage,
        symbol=resolved_symbol,
        mode=resolved_mode,
        time_from=resolved_time_from,
        time_to=resolved_time_to,
        status=resolved_status,
        evidence_type=resolved_evidence_type,
        limit=SUPERVISOR_QUERY_DEFAULT_LIMIT,
        cursor=None,
    )
    return SupervisorKnowledgeHistoryPlan(
        True, "OBSERVATION_SCOPED", query, tuple(notes), scope
    )


def _envelope(reason: str, *, fallback: bool, notes: Tuple[str, ...] = ()) -> dict:
    metadata = {
        "knowledge_history_used": False,
        "query_summary": {
            "filters": None,
            "requested_limit": SUPERVISOR_QUERY_DEFAULT_LIMIT,
            "resolved_limit": None,
            "returned_count": 0,
            "has_more": False,
            "notes": list(notes),
        },
        "returned_count": 0,
        "items": [],
        "sources": [],
        "provenance": [],
        "freshness": {},
        "availability": {},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
        "uncertainty": "HIGH" if fallback else "UNKNOWN",
        "fallback": fallback,
        "truncated": False,
        "reason": reason,
    }
    return metadata


class SupervisorKnowledgeHistoryConsumer:
    """Read-only request-time bridge to the shared knowledge/history service.

    Construction is side-effect free.  The shared service is resolved lazily on
    the first real query, so a disabled consumer never constructs or touches the
    shared query layer.
    """

    def __init__(
        self,
        facade: Optional[KnowledgeHistoryQueryFacade] = None,
        *,
        environ: Optional[Mapping[str, str]] = None,
        time_window_seconds: float = SUPERVISOR_DEFAULT_TIME_WINDOW_SECONDS,
    ):
        self._facade = facade
        self._environ = environ
        self._time_window_seconds = time_window_seconds

    @property
    def enabled(self) -> bool:
        return supervisor_knowledge_history_enabled(self._environ)

    def _resolve_facade(self) -> KnowledgeHistoryQueryFacade:
        if self._facade is None:
            self._facade = shared_knowledge_history_facade()
        return self._facade

    def metadata_for_snapshot(self, snapshot: Any, **filters: Any) -> Optional[dict]:
        """Return optional Supervisor metadata, or ``None`` when the flag is OFF.

        A ``None`` return means the existing snapshot output is untouched (no
        knowledge-history key is added).
        """

        if not self.enabled:
            return None
        try:
            plan = plan_supervisor_query(
                snapshot,
                time_window_seconds=self._time_window_seconds,
                **filters,
            )
        except Exception:  # noqa: BLE001 - planning must never break the snapshot
            return _envelope("PLANNING_FAILED", fallback=True)
        if not plan.relevant or plan.query is None:
            return _envelope(plan.reason, fallback=False, notes=plan.notes)
        try:
            result = self._resolve_facade().query(plan.query)
        except Exception as exc:  # noqa: BLE001 - one failed query must not break the snapshot
            return _envelope("QUERY_FAILED", fallback=True, notes=(type(exc).__name__,))
        try:
            context = assemble_knowledge_history_context(
                result,
                plan,
                max_items=SUPERVISOR_CONTEXT_MAX_ITEMS,
                max_characters=SUPERVISOR_CONTEXT_MAX_CHARACTERS,
                requested_limit=SUPERVISOR_QUERY_DEFAULT_LIMIT,
            )
        except Exception:  # noqa: BLE001 - assembly must never break the snapshot
            return _envelope("CONTEXT_ASSEMBLY_FAILED", fallback=True)
        if plan.scope:
            context["query_summary"]["scope"] = plan.scope
        return context
