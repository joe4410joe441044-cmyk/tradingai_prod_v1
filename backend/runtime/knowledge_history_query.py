"""Shared read-only knowledge/history query service (WORK I②).

Advisor and Supervisor use this *same* service instance; neither gets its own
knowledge store.  The service:

* validates the optional query filters and rejects secrets;
* enforces a bounded ``limit`` and an opaque, verified cursor;
* selects sources and refuses to silently ignore an unsupported filter (the
  affected source is reported as ``UNSUPPORTED_FILTER`` instead);
* normalizes, de-duplicates and deterministically orders the merged items;
* attaches provenance / freshness / availability per source;
* isolates a failing or corrupt source so the other sources still return.

It never writes, never re-runs a producer/detector, never calls an LLM and
never performs network access.  Importing and constructing it performs no I/O.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterable, Mapping, Optional, Sequence

from backend.runtime.cycle_evidence import (
    AvailabilityState,
    EvidenceType,
    stable_fingerprint,
)
from backend.runtime.cycle_evidence_stage_inputs import (
    StageResolutionError,
    resolve_stage,
)
from backend.runtime.knowledge_history_models import (
    ConsumerKind,
    CURSOR_VERSION,
    DEFAULT_QUERY_LIMIT,
    FreshnessPolicy,
    KnowledgeHistoryCursorError,
    KnowledgeHistoryQuery,
    KnowledgeHistoryQueryError,
    MAX_QUERY_LIMIT,
    SourceAvailability,
    utc_now,
    to_iso,
    parse_timestamp,
)
from backend.runtime.knowledge_history_sanitizer import assert_query_safe
from backend.runtime.knowledge_history_sources import (
    SOURCE_CATALOG,
    CycleEvidenceSource,
    SourcePage,
    TradingTraceSource,
    capability_for,
    source_catalog,
)


KNOWLEDGE_HISTORY_CONSUMERS_ENABLED_ENV = "KNOWLEDGE_HISTORY_QUERY_CONSUMERS_ENABLED"


def _encode_cursor(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - any malformed cursor is rejected
        raise KnowledgeHistoryCursorError(
            "CURSOR_INVALID", "cursor is not a valid knowledge-history cursor"
        ) from exc
    if not isinstance(payload, dict):
        raise KnowledgeHistoryCursorError("CURSOR_INVALID", "cursor payload is not an object")
    return payload


def _normalized_source_selection(source: Optional[Iterable[str]]) -> tuple[str, ...]:
    if source is None:
        return tuple(capability.source for capability in SOURCE_CATALOG)
    selected: list[str] = []
    for value in source:
        if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
            value = value.value
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeHistoryQueryError(
                "INVALID_SOURCE", "source must be a non-empty source name"
            )
        name = value.strip().upper()
        try:
            capability_for(name)
        except KeyError as exc:
            raise KnowledgeHistoryQueryError(
                "UNKNOWN_SOURCE", f"unknown query source: {value!r}"
            ) from exc
        if name not in selected:
            selected.append(name)
    if not selected:
        raise KnowledgeHistoryQueryError("INVALID_SOURCE", "at least one source is required")
    order = {capability.source: index for index, capability in enumerate(SOURCE_CATALOG)}
    return tuple(sorted(selected, key=lambda name: order[name]))


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeHistoryQueryError(
            f"INVALID_{field.upper()}", f"{field} must be a non-empty string"
        )
    return value.strip()


def _normalize_query(raw: KnowledgeHistoryQuery) -> KnowledgeHistoryQuery:
    if not isinstance(raw, KnowledgeHistoryQuery):
        raise KnowledgeHistoryQueryError("INVALID_QUERY", "query must be a KnowledgeHistoryQuery")

    selected = _normalized_source_selection(raw.source)

    cycle_id = _require_text(raw.cycle_id, "cycle_id") if raw.cycle_id is not None else None
    trace_id = _require_text(raw.trace_id, "trace_id") if raw.trace_id is not None else None
    evidence_id = _require_text(raw.evidence_id, "evidence_id") if raw.evidence_id is not None else None
    symbol = raw.symbol.strip().upper() if isinstance(raw.symbol, str) and raw.symbol.strip() else None

    mode = raw.mode.strip().upper() if isinstance(raw.mode, str) else None
    if mode is not None and mode not in ("PAPER", "LIVE"):
        raise KnowledgeHistoryQueryError("INVALID_MODE", "mode must be PAPER or LIVE")

    evidence_type = raw.evidence_type.strip().upper() if isinstance(raw.evidence_type, str) else None
    if evidence_type is not None and evidence_type not in {item.value for item in EvidenceType}:
        raise KnowledgeHistoryQueryError(
            "INVALID_EVIDENCE_TYPE", f"unknown evidence_type: {raw.evidence_type!r}"
        )

    stage = raw.stage
    stage_name = raw.stage_name.strip().upper() if isinstance(raw.stage_name, str) else None
    if stage is not None or stage_name is not None:
        try:
            definition = resolve_stage(stage=stage, stage_name=stage_name)
        except StageResolutionError as exc:
            raise KnowledgeHistoryQueryError("INVALID_STAGE", str(exc)) from exc
        stage, stage_name = definition.number, definition.name

    availability = None
    if raw.availability:
        values = tuple(str(value).strip().upper() for value in raw.availability)
        known = {state.value for state in AvailabilityState}
        unknown = [value for value in values if value not in known]
        if unknown:
            raise KnowledgeHistoryQueryError(
                "INVALID_AVAILABILITY", f"unknown availability state(s): {unknown!r}"
            )
        availability = values

    for label, value in (("time_from", raw.time_from), ("time_to", raw.time_to)):
        if value is not None and parse_timestamp(value) is None:
            raise KnowledgeHistoryQueryError(
                "INVALID_TIME_RANGE", f"{label} is not a valid ISO-8601/epoch time"
            )

    limit = raw.limit
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise KnowledgeHistoryQueryError("INVALID_LIMIT", "limit must be an integer")
        if limit < 1:
            raise KnowledgeHistoryQueryError("INVALID_LIMIT", "limit must be >= 1")

    cursor = raw.cursor if isinstance(raw.cursor, str) and raw.cursor else None

    assert_query_safe(
        {
            "cycle_id": cycle_id,
            "trace_id": trace_id,
            "evidence_id": evidence_id,
            "stage": stage,
            "stage_name": stage_name,
            "symbol": symbol,
            "mode": mode,
            "time_from": raw.time_from,
            "time_to": raw.time_to,
            "status": raw.status,
            "evidence_type": evidence_type,
            "availability": availability,
        }
    )

    return KnowledgeHistoryQuery(
        cycle_id=cycle_id,
        trace_id=trace_id,
        evidence_id=evidence_id,
        stage=stage,
        stage_name=stage_name,
        symbol=symbol,
        mode=mode,
        time_from=raw.time_from,
        time_to=raw.time_to,
        status=_require_text(raw.status, "status") if raw.status is not None else None,
        evidence_type=evidence_type,
        source=selected,
        availability=availability,
        limit=limit,
        cursor=cursor,
    )


@dataclass(frozen=True)
class _SourcePlan:
    source: str
    supported: bool
    unsupported_filters: tuple[str, ...]


class KnowledgeHistoryQueryService:
    """The single shared read-only query service for Advisor and Supervisor."""

    def __init__(
        self,
        sources: Optional[Sequence[Any]] = None,
        *,
        policy: Optional[FreshnessPolicy] = None,
        default_limit: int = DEFAULT_QUERY_LIMIT,
        max_limit: int = MAX_QUERY_LIMIT,
    ):
        if sources is None:
            sources = [CycleEvidenceSource(), TradingTraceSource()]
        self._sources = {source.source: source for source in sources}
        self.policy = policy if policy is not None else FreshnessPolicy()
        self.max_limit = max(1, int(max_limit))
        self.default_limit = max(1, min(int(default_limit), self.max_limit))

    # -- public API ----------------------------------------------------------

    def query(self, query: Optional[KnowledgeHistoryQuery] = None, **kwargs: Any) -> dict:
        """Run one bounded, read-only query and return the shared result contract."""

        validated = _normalize_query(query if query is not None else KnowledgeHistoryQuery(**kwargs))
        limit = self._resolve_limit(validated.limit)

        selected = tuple(validated.source or ())
        fingerprint = stable_fingerprint(validated.fingerprint_value())
        cursors, exhausted, rotation = self._resolve_global_cursor(
            validated.cursor, fingerprint, selected
        )

        plans = self._plan_sources(validated, selected)
        supported = [plan.source for plan in plans if plan.supported]
        active = [name for name in supported if name not in exhausted]

        if limit >= len(active):
            window = list(active)
            budgets = self._split_budget(limit, active)
            rotation_next = 0
            deferred: list[str] = []
        else:
            count = len(active)
            start = rotation % max(1, count)
            window = [active[(start + index) % count] for index in range(limit)]
            budgets = {name: 1 for name in window}
            rotation_next = (start + limit) % count
            deferred = [name for name in active if name not in set(window)]

        reports: list[dict] = []
        provenance: list[dict] = []
        freshness_records: list[dict] = []
        unsupported_filters: list[dict] = []
        warnings: list[str] = []
        pages: dict[str, SourcePage] = {}
        now = utc_now()

        for plan in plans:
            if plan.supported:
                continue
            for name in plan.unsupported_filters:
                unsupported_filters.append(
                    {
                        "source": plan.source,
                        "filter": name,
                        "reason": "SOURCE_CANNOT_EVALUATE_FILTER",
                    }
                )
            warnings.append(
                f"{plan.source}:UNSUPPORTED_FILTERS:{','.join(plan.unsupported_filters)}"
            )
            capability = capability_for(plan.source)
            provenance.append(self._capability_provenance(capability))
            freshness_records.append(
                self.policy.evaluate(
                    source=plan.source,
                    observed_at=None,
                    now=now,
                    reason_unavailable="SOURCE_NOT_QUERIED_UNSUPPORTED_FILTER",
                )
            )
            reports.append(
                {
                    "source": plan.source,
                    "availability": SourceAvailability.UNSUPPORTED_FILTER.value,
                    "items_returned": 0,
                    "corruption_count": 0,
                    "bounded": True,
                    "read_method": capability.read_method,
                    "error": None,
                    "warnings": [f"UNSUPPORTED_FILTERS:{','.join(plan.unsupported_filters)}"],
                    "next_cursor": None,
                    "has_more": False,
                }
            )

        for name in window:
            pages[name] = self._read_source(
                self._sources[name], validated, limits=budgets, cursors=cursors
            )
        for name in deferred:
            warnings.append(f"SOURCE_DEFERRED:{name}")

        # -- merge / de-duplicate / deterministic ordering -------------------
        seen: set[str] = set()
        merged: list[dict] = []
        for source_name in window:
            page = pages.get(source_name)
            if page is None:
                continue
            for item in page.items:
                key = str(item.get("event_key"))
                if key in seen:
                    warnings.append(f"DEDUPLICATED:{source_name}:{key}")
                    continue
                seen.add(key)
                merged.append(item)
        merged.sort(
            key=lambda item: (
                parse_timestamp(item.get("captured_at")) or 0.0,
                str(item.get("event_key")),
            )
        )
        if len(merged) > limit:
            merged = merged[:limit]

        # -- per-source reports for queried sources --------------------------
        overall_has_more = bool(deferred)
        source_cursors: dict[str, Optional[str]] = {}
        finished: list[str] = []
        for source_name in window:
            page = pages[source_name]
            source_cursors[source_name] = page.next_cursor if page.has_more else None
            if not page.has_more:
                finished.append(source_name)
            overall_has_more = overall_has_more or page.has_more
            reports.append(self._source_report(page))
            provenance.append(page.provenance)
            freshness_records.append(
                self.policy.evaluate(
                    source=source_name,
                    observed_at=page.observed_at,
                    now=now,
                    source_revision=page.source_revision,
                )
            )
            warnings.extend(f"{source_name}:{warning}" for warning in page.warnings)
        for name in deferred:
            source_cursors[name] = cursors.get(name)

        available_states = [report["availability"] for report in reports]
        unavailable = {
            SourceAvailability.ERROR.value,
            SourceAvailability.UNSUPPORTED_FILTER.value,
            SourceAvailability.NOT_AVAILABLE.value,
            SourceAvailability.PARTIAL.value,
        }
        partial_result = any(state in unavailable for state in available_states)
        corruption_count = sum(int(report["corruption_count"]) for report in reports)

        if partial_result:
            warnings.append("PARTIAL_RESULT")

        next_cursor = None
        if overall_has_more:
            next_cursor = _encode_cursor(
                {
                    "v": CURSOR_VERSION,
                    "q": fingerprint,
                    "c": source_cursors,
                    "d": finished,
                    "r": rotation_next,
                }
            )

        return {
            "query": validated.to_dict(),
            "items": merged,
            "returned_count": len(merged),
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": overall_has_more,
            "sources": reports,
            "provenance": provenance,
            "freshness": {
                "overall": self._aggregate_freshness(freshness_records),
                "sources": freshness_records,
            },
            "availability": {
                "overall": self._aggregate_availability(available_states),
                "by_source": {report["source"]: report["availability"] for report in reports},
            },
            "unsupported_filters": unsupported_filters,
            "warnings": warnings,
            "corruption_count": corruption_count,
            "partial_result": partial_result,
            "generated_at": to_iso(now),
        }

    # -- internals -----------------------------------------------------------

    def _resolve_limit(self, limit: Optional[int]) -> int:
        if limit is None:
            return self.default_limit
        return max(1, min(int(limit), self.max_limit))

    def _plan_sources(
        self, query: KnowledgeHistoryQuery, selected: tuple[str, ...]
    ) -> list[_SourcePlan]:
        requested = set(query.requested_filters())
        plans: list[_SourcePlan] = []
        for name in selected:
            capability = capability_for(name)
            unsupported = tuple(sorted(requested - capability.filters))
            plans.append(_SourcePlan(source=name, supported=not unsupported, unsupported_filters=unsupported))
        return plans

    @staticmethod
    def _split_budget(limit: int, names: Sequence[str]) -> dict[str, int]:
        if not names:
            return {}
        base, remainder = divmod(limit, len(names))
        return {
            name: max(1, base + (1 if index < remainder else 0))
            for index, name in enumerate(names)
        }

    def _resolve_global_cursor(
        self, cursor: Optional[str], fingerprint: str, selected: tuple[str, ...]
    ) -> tuple[dict[str, Optional[str]], set[str], int]:
        if cursor is None:
            return {name: None for name in selected}, set(), 0
        payload = _decode_cursor(cursor)
        if payload.get("v") != CURSOR_VERSION:
            raise KnowledgeHistoryCursorError(
                "CURSOR_VERSION_UNSUPPORTED", "cursor version is not supported"
            )
        if payload.get("q") != fingerprint:
            raise KnowledgeHistoryCursorError(
                "CURSOR_QUERY_MISMATCH", "cursor was issued for a different query"
            )
        stored = payload.get("c")
        if not isinstance(stored, Mapping) or set(stored) != set(selected):
            raise KnowledgeHistoryCursorError(
                "CURSOR_SOURCE_MISMATCH", "cursor source set does not match the query"
            )
        exhausted = payload.get("d")
        if exhausted is None:
            exhausted_set: set[str] = set()
        elif isinstance(exhausted, list) and all(isinstance(name, str) for name in exhausted):
            exhausted_set = set(exhausted)
        else:
            raise KnowledgeHistoryCursorError("CURSOR_INVALID", "cursor exhausted set is malformed")
        rotation = payload.get("r", 0)
        if not isinstance(rotation, int) or isinstance(rotation, bool) or rotation < 0:
            raise KnowledgeHistoryCursorError("CURSOR_INVALID", "cursor rotation is malformed")
        return {name: stored.get(name) for name in selected}, exhausted_set, rotation

    def _read_source(
        self,
        source: Any,
        query: KnowledgeHistoryQuery,
        *,
        limits: dict[str, int],
        cursors: dict[str, Optional[str]],
    ) -> SourcePage:
        name = source.source
        try:
            return source.read(query, limit=limits.get(name, 1), cursor=cursors.get(name))
        except Exception as exc:  # noqa: BLE001 - isolate one source failure
            capability = capability_for(name)
            return SourcePage(
                source=name,
                items=[],
                next_cursor=None,
                has_more=False,
                corruption_count=0,
                warnings=[f"SOURCE_ERROR:{type(exc).__name__}"],
                availability=SourceAvailability.ERROR.value,
                observed_at=None,
                source_revision=None,
                provenance=self._capability_provenance(capability, error=str(exc)),
            )

    @staticmethod
    def _capability_provenance(capability: Any, error: Optional[str] = None) -> dict:
        record = {
            "source_type": capability.source,
            "authority": capability.authority,
            "source_path": None,
            "source_revision": None,
            "read_method": capability.read_method,
            "bounded_read": capability.bounded,
            "integrity": "UNKNOWN",
        }
        if error is not None:
            record["error"] = error
        return record

    @staticmethod
    def _source_report(page: SourcePage) -> dict:
        return {
            "source": page.source,
            "availability": page.availability,
            "items_returned": len(page.items),
            "corruption_count": page.corruption_count,
            "bounded": page.bounded,
            "read_method": page.provenance.get("read_method"),
            "error": None,
            "warnings": list(page.warnings),
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
        }

    @staticmethod
    def _aggregate_freshness(records: Sequence[Mapping[str, Any]]) -> str:
        states = {str(record.get("state")) for record in records}
        if "STALE" in states:
            return "STALE"
        if "UNKNOWN" in states:
            return "UNKNOWN"
        if "FRESH" in states:
            return "FRESH"
        return "NOT_APPLICABLE"

    @staticmethod
    def _aggregate_availability(states: Sequence[str]) -> str:
        if not states:
            return SourceAvailability.NOT_AVAILABLE.value
        if all(state in (SourceAvailability.ERROR.value, SourceAvailability.NOT_AVAILABLE.value) for state in states):
            return SourceAvailability.NOT_AVAILABLE.value
        if any(
            state
            in (
                SourceAvailability.ERROR.value,
                SourceAvailability.PARTIAL.value,
                SourceAvailability.UNSUPPORTED_FILTER.value,
                SourceAvailability.NOT_AVAILABLE.value,
            )
            for state in states
        ):
            return SourceAvailability.PARTIAL.value
        return SourceAvailability.AVAILABLE.value


class KnowledgeHistoryQueryFacade:
    """Thin read-only facade a consumer may hold (no production wiring)."""

    def __init__(self, service: KnowledgeHistoryQueryService):
        self._service = service

    @property
    def service(self) -> KnowledgeHistoryQueryService:
        return self._service

    def query(self, query: Optional[KnowledgeHistoryQuery] = None, **kwargs: Any) -> dict:
        return self._service.query(query, **kwargs)

    def catalog(self) -> list[dict]:
        return source_catalog()


# One shared service instance for every consumer.  Advisor and Supervisor must
# never each build their own knowledge store.
_SHARED_LOCK = Lock()
_SHARED_SERVICE: Optional[KnowledgeHistoryQueryService] = None


def default_knowledge_history_query_service() -> KnowledgeHistoryQueryService:
    global _SHARED_SERVICE
    with _SHARED_LOCK:
        if _SHARED_SERVICE is None:
            _SHARED_SERVICE = KnowledgeHistoryQueryService(
                sources=[CycleEvidenceSource(), TradingTraceSource()]
            )
        return _SHARED_SERVICE


def shared_knowledge_history_facade() -> KnowledgeHistoryQueryFacade:
    return KnowledgeHistoryQueryFacade(default_knowledge_history_query_service())


def consumer_facade(kind: Any) -> KnowledgeHistoryQueryFacade:
    """Return the shared facade for an Advisor/Supervisor consumer."""

    value = kind.value if isinstance(kind, ConsumerKind) else str(kind)
    if value not in {member.value for member in ConsumerKind}:
        raise KnowledgeHistoryQueryError("UNKNOWN_CONSUMER", f"unknown consumer: {kind!r}")
    return shared_knowledge_history_facade()


def knowledge_history_consumers_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Consumer-exposure flag; default OFF and independent of Phase A."""

    env = os.environ if environ is None else environ
    raw = str(env.get(KNOWLEDGE_HISTORY_CONSUMERS_ENABLED_ENV, "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def consumer_capabilities() -> dict:
    """Capability metadata for the (not yet wired) Advisor/Supervisor consumers."""

    return {
        "AI_ADVISOR": {
            "consumer": "AI_ADVISOR",
            "read_only": True,
            "shared_service": True,
            "writes": False,
            "llm_calls": False,
            "conversation_write": False,
            "api_route": None,
        },
        "AI_SUPERVISOR": {
            "consumer": "AI_SUPERVISOR",
            "read_only": True,
            "shared_service": True,
            "writes": False,
            "llm_calls": False,
            "scheduler_registration": False,
            "supervisor_audit_write": False,
            "api_route": None,
        },
    }
