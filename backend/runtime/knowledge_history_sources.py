"""Read-only source adapters for the shared knowledge/history query layer.

Each adapter wraps an *existing* canonical authority and never writes it:

* :class:`CycleEvidenceSource` reads the durable canonical evidence envelopes
  through :class:`~backend.runtime.cycle_evidence_store.CycleEvidenceStore`'s
  bounded streaming read;
* :class:`TradingTraceSource` reads the durable trading trace through the
  restart-safe bounded :class:`~backend.runtime.trading_trace_reader.TradingTraceReader`
  and projects each event with the canonical
  :func:`~backend.runtime.cycle_evidence_links.trace_event_evidence` link
  adapter;
* :class:`CycleEvidenceLinkResolver` resolves canonical runtime/decision/trade
  identity links (reusing the link projection module, never re-implementing it).

Nothing here writes, re-runs a producer/detector, or talks to the network.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, FrozenSet, Mapping, Optional

from backend.runtime.cycle_evidence import (
    CycleEvidenceError,
    LIFECYCLE_STAGE_NAMES,
)
from backend.runtime.cycle_evidence_links import trace_event_evidence
from backend.runtime.cycle_evidence_store import CycleEvidenceStore
from backend.runtime.knowledge_history_models import (
    KnowledgeHistoryCursorError,
    KnowledgeHistoryQuery,
    KnowledgeSource,
    MAX_QUERY_LIMIT,
    parse_timestamp,
)
from backend.runtime.knowledge_history_sanitizer import sanitize_summary
from backend.runtime.trading_trace_reader import TradingTraceReader

# A bounded scan guard for the line-oriented cycle evidence read.  The trading
# trace reader has its own byte/line/timeout budgets; this one keeps the store
# read from ever becoming an unbounded whole-file walk.
CYCLE_EVIDENCE_MAX_SCAN_RECORDS = 50_000

CYCLE_EVIDENCE_FILTERS: FrozenSet[str] = frozenset(
    {
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
    }
)

# The trace authority has no evidence identifier, so a query filtered by
# ``evidence_id`` cannot be answered from it and must not be silently ignored.
TRADING_TRACE_FILTERS: FrozenSet[str] = frozenset(
    {
        "cycle_id",
        "trace_id",
        "stage",
        "stage_name",
        "symbol",
        "mode",
        "time_range",
        "status",
        "evidence_type",
        "availability",
    }
)


@dataclass(frozen=True)
class SourceCapability:
    """Declared capability of one read-only source."""

    source: str
    filters: FrozenSet[str]
    authority: str
    read_method: str
    bounded: bool = True
    writable: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "filters": sorted(self.filters),
            "authority": self.authority,
            "read_method": self.read_method,
            "bounded": self.bounded,
            "writable": self.writable,
        }


SOURCE_CATALOG: tuple[SourceCapability, ...] = (
    SourceCapability(
        source=KnowledgeSource.CYCLE_EVIDENCE.value,
        filters=CYCLE_EVIDENCE_FILTERS,
        authority="backend.runtime.cycle_evidence_store.CycleEvidenceStore",
        read_method="CycleEvidenceStore.iter_records",
    ),
    SourceCapability(
        source=KnowledgeSource.TRADING_TRACE.value,
        filters=TRADING_TRACE_FILTERS,
        authority="backend.runtime.trading_trace_reader.TradingTraceReader",
        read_method="TradingTraceReader.query_events+trace_event_evidence",
    ),
)


def source_catalog() -> list[dict]:
    return [capability.to_dict() for capability in SOURCE_CATALOG]


def capability_for(source: str) -> SourceCapability:
    for capability in SOURCE_CATALOG:
        if capability.source == source:
            return capability
    raise KeyError(source)


@dataclass
class SourcePage:
    """One bounded page read from one source (read-only)."""

    source: str
    items: list[dict] = field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False
    corruption_count: int = 0
    warnings: list[str] = field(default_factory=list)
    availability: str = "AVAILABLE"
    observed_at: Optional[str] = None
    source_revision: Optional[str] = None
    provenance: dict = field(default_factory=dict)
    bounded: bool = True

    @property
    def event_keys(self) -> list[str]:
        return [str(item.get("event_key")) for item in self.items]


def _encode_position(position: int) -> str:
    return base64.urlsafe_b64encode(str(position).encode("utf-8")).decode("ascii").rstrip("=")


def _decode_position(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
    except Exception as exc:  # noqa: BLE001 - any malformed cursor is rejected
        raise KnowledgeHistoryCursorError(
            "CURSOR_INVALID", "cursor is not a valid cycle-evidence cursor"
        ) from exc


def _mtime_iso(path: Path) -> Optional[str]:
    try:
        import datetime as _dt

        stat = path.stat()
    except OSError:
        return None
    return (
        _dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _size_revision(path: Path) -> Optional[str]:
    try:
        return f"size={path.stat().st_size}"
    except OSError:
        return None


def _stage_name(stage: Any) -> Optional[str]:
    if isinstance(stage, bool) or not isinstance(stage, int):
        return None
    return LIFECYCLE_STAGE_NAMES.get(int(stage))


def _availability_states(availability: Mapping[str, Any]) -> set[str]:
    states: set[str] = set()
    for entry in (availability or {}).values():
        if isinstance(entry, str):
            states.add(entry)
        elif isinstance(entry, Mapping) and isinstance(entry.get("state"), str):
            states.add(entry["state"])
    return states


def _matches_common(item: Mapping[str, Any], query: KnowledgeHistoryQuery) -> bool:
    """Apply every optional filter over a normalized item."""

    if query.cycle_id is not None and item.get("cycle_id") != query.cycle_id:
        return False
    if query.trace_id is not None and item.get("trace_id") != query.trace_id:
        return False
    if query.evidence_id is not None and item.get("evidence_id") != query.evidence_id:
        return False
    if query.stage is not None and item.get("stage") != query.stage:
        return False
    if query.stage_name is not None:
        if str(item.get("stage_name") or "").upper() != query.stage_name.upper():
            return False
    if query.symbol is not None:
        if str(item.get("symbol") or "").upper() != query.symbol.upper():
            return False
    if query.mode is not None:
        if str(item.get("mode") or "").upper() != query.mode.upper():
            return False
    if query.status is not None:
        if str(item.get("status") or "").upper() != query.status.upper():
            return False
    if query.evidence_type is not None:
        if str(item.get("evidence_type") or "").upper() != query.evidence_type.upper():
            return False
    if query.availability:
        requested = {str(value) for value in query.availability}
        if not (_availability_states(item.get("availability") or {}) & requested):
            return False
    if query.time_from is not None or query.time_to is not None:
        captured = parse_timestamp(item.get("captured_at"))
        if captured is None:
            return False
        lower = parse_timestamp(query.time_from)
        upper = parse_timestamp(query.time_to)
        if lower is not None and captured < lower:
            return False
        if upper is not None and captured >= upper:
            return False
    return True


def _item_from_envelope(
    envelope: Mapping[str, Any],
    *,
    source: str,
    read_method: str,
    integrity: str,
) -> dict:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), Mapping) else {}
    links = envelope.get("links") if isinstance(envelope.get("links"), Mapping) else {}
    payload_summary, payload_redacted = sanitize_summary(payload)
    link_summary, links_redacted = sanitize_summary(links)
    source_block = envelope.get("source") if isinstance(envelope.get("source"), Mapping) else {}
    source_record_id = envelope.get("source_record_id")
    event_key = (
        f"{source}:{source_record_id}"
        if source_record_id
        else f"{source}:{envelope.get('evidence_id') or envelope.get('event_id')}"
    )
    stage = envelope.get("lifecycle_stage")
    return {
        "source": source,
        "event_key": event_key,
        "evidence_id": envelope.get("evidence_id"),
        "cycle_id": envelope.get("cycle_id"),
        "trace_id": envelope.get("correlation_id"),
        "stage": stage,
        "stage_name": _stage_name(stage),
        "status": payload.get("status"),
        "evidence_type": envelope.get("evidence_type"),
        "symbol": envelope.get("symbol"),
        "mode": envelope.get("mode"),
        "event_id": envelope.get("event_id"),
        "captured_at": envelope.get("occurred_at") or envelope.get("recorded_at"),
        "source_reference": {
            "subsystem": source_block.get("subsystem"),
            "module": source_block.get("module"),
        },
        "links": link_summary,
        "payload": payload_summary,
        "availability": dict(envelope.get("availability") or {}),
        "provenance": {
            "source_type": source,
            "source_record_id": source_record_id,
            "read_method": read_method,
            "bounded_read": True,
            "integrity": integrity,
            "redacted": payload_redacted or links_redacted,
        },
    }


class CycleEvidenceSource:
    """Read-only adapter over :class:`CycleEvidenceStore`."""

    source = KnowledgeSource.CYCLE_EVIDENCE.value

    def __init__(
        self,
        store: Optional[CycleEvidenceStore] = None,
        *,
        max_scan_records: int = CYCLE_EVIDENCE_MAX_SCAN_RECORDS,
    ):
        self.store = store if store is not None else CycleEvidenceStore()
        self.max_scan_records = max(1, int(max_scan_records))

    @property
    def path(self) -> Path:
        return Path(self.store.path)

    def read(self, query: KnowledgeHistoryQuery, *, limit: int, cursor: Optional[str]) -> SourcePage:
        limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
        start_after = _decode_position(cursor) if cursor else 0
        items: list[dict] = []
        corruption = 0
        scanned = 0
        last_position = start_after
        has_more = False
        warnings: list[str] = []

        for record in self.store.iter_records():
            if record.position <= start_after:
                continue
            scanned += 1
            if scanned > self.max_scan_records:
                has_more = True
                warnings.append("SCAN_RECORD_BUDGET_EXHAUSTED")
                break
            if not record.valid:
                corruption += 1
                continue
            item = _item_from_envelope(
                record.record,
                source=self.source,
                read_method="CycleEvidenceStore.iter_records",
                integrity="VERIFIED",
            )
            if not _matches_common(item, query):
                last_position = record.position
                continue
            if len(items) >= limit:
                has_more = True
                break
            items.append(item)
            last_position = record.position

        exists = self.path.exists()
        if not exists:
            availability = "NOT_AVAILABLE"
        elif has_more and warnings:
            availability = "PARTIAL"
        elif not items and not has_more:
            availability = "EMPTY"
        else:
            availability = "AVAILABLE"

        observed_at = _mtime_iso(self.path)
        revision = _size_revision(self.path)
        provenance = {
            "source_type": self.source,
            "authority": "backend.runtime.cycle_evidence_store.CycleEvidenceStore",
            "source_path": str(self.path),
            "source_revision": revision,
            "read_method": "CycleEvidenceStore.iter_records",
            "bounded_read": True,
            "integrity": "VERIFIED" if exists else "UNKNOWN",
        }
        observed_at = observed_at if exists else None
        return SourcePage(
            source=self.source,
            items=items,
            next_cursor=_encode_position(last_position) if has_more else None,
            has_more=has_more,
            corruption_count=corruption,
            warnings=warnings,
            availability=availability,
            observed_at=observed_at,
            source_revision=revision,
            provenance=provenance,
        )


class TradingTraceSource:
    """Read-only adapter over :class:`TradingTraceReader`."""

    source = KnowledgeSource.TRADING_TRACE.value

    def __init__(self, reader: Optional[TradingTraceReader] = None):
        self.reader = reader if reader is not None else TradingTraceReader()

    @property
    def path(self) -> Path:
        return Path(self.reader.path)

    def read(self, query: KnowledgeHistoryQuery, *, limit: int, cursor: Optional[str]) -> SourcePage:
        limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
        try:
            page = self.reader.query_events(
                time_from=query.time_from,
                time_to=query.time_to,
                cycle_id=query.cycle_id,
                correlation_id=query.trace_id,
                mode=query.mode,
                status=query.status,
                symbol=query.symbol,
                limit=limit,
                cursor=cursor,
                direction="forward",
            )
        except Exception as exc:  # noqa: BLE001 - a bad cursor must surface structurally
            code = getattr(exc, "code", "CURSOR_INVALID")
            raise KnowledgeHistoryCursorError(
                "CURSOR_INVALID", f"trading trace cursor rejected: {code}"
            ) from exc

        items: list[dict] = []
        corruption = 0
        warnings: list[str] = []
        for event in page.get("events", []):
            try:
                envelope = trace_event_evidence(event).to_dict()
            except (CycleEvidenceError, ValueError, TypeError, KeyError) as exc:
                corruption += 1
                warnings.append(f"TRACE_EVENT_ISOLATED:{type(exc).__name__}")
                continue
            item = _item_from_envelope(
                envelope,
                source=self.source,
                read_method="TradingTraceReader.query_events+trace_event_evidence",
                integrity="UNKNOWN",
            )
            if not _matches_common(item, query):
                continue
            items.append(item)

        scan = page.get("scan", {}) if isinstance(page.get("scan"), Mapping) else {}
        file_block = page.get("file", {}) if isinstance(page.get("file"), Mapping) else {}
        corruption += int(scan.get("isolatedRecords") or 0)
        if scan.get("partial"):
            warnings.append(f"TRACE_SCAN_PARTIAL:{scan.get('reason')}")

        exists = bool(file_block.get("exists"))
        if not exists:
            availability = "NOT_AVAILABLE"
        elif scan.get("partial"):
            availability = "PARTIAL"
        elif page.get("count", 0) == 0:
            availability = "EMPTY"
        else:
            availability = "AVAILABLE"

        snapshot = self.reader.snapshot()
        revision = f"size={snapshot.size};head={snapshot.head[:16]}" if snapshot.exists else None
        observed_at = _mtime_iso(self.path) if exists else None
        provenance = {
            "source_type": self.source,
            "authority": "backend.runtime.trading_trace_reader.TradingTraceReader",
            "source_path": str(self.path),
            "source_revision": revision,
            "read_method": "TradingTraceReader.query_events+trace_event_evidence",
            "bounded_read": True,
            "integrity": "UNKNOWN",
            "scan_partial": bool(scan.get("partial")),
        }
        return SourcePage(
            source=self.source,
            items=items,
            next_cursor=page.get("pagination", {}).get("nextCursor"),
            has_more=bool(page.get("pagination", {}).get("hasMore")),
            corruption_count=corruption,
            warnings=warnings,
            availability=availability,
            observed_at=observed_at,
            source_revision=revision,
            provenance=provenance,
        )


class CycleEvidenceLinkResolver:
    """Resolve canonical runtime/decision/trade identity links, read-only.

    Link extraction is delegated to the canonical
    :mod:`backend.runtime.cycle_evidence_links` projection module; this class
    only exposes it as a bounded resolver and never re-implements the mapping.
    """

    def __init__(self, store: Optional[CycleEvidenceStore] = None):
        self.store = store if store is not None else CycleEvidenceStore()

    def project_trace_event(self, event: Mapping[str, Any]) -> Optional[dict]:
        """Project one trace event into a canonical envelope (or ``None``)."""

        try:
            return trace_event_evidence(event).to_dict()
        except (CycleEvidenceError, ValueError, TypeError, KeyError):
            return None

    def resolve_by_evidence_id(self, evidence_id: str) -> Optional[dict]:
        """Return the canonical links for one evidence id, read-only."""

        if not isinstance(evidence_id, str) or not evidence_id:
            return None
        record = self.store.get(evidence_id)
        if not record:
            return None
        links = record.get("links") if isinstance(record.get("links"), Mapping) else {}
        summary, _ = sanitize_summary(links)
        return {
            "evidence_id": evidence_id,
            "cycle_id": record.get("cycle_id"),
            "trace_id": record.get("correlation_id"),
            "links": summary,
        }

    def resolve_by_cycle_id(
        self, cycle_id: str, *, limit: int = 50, max_scan_records: int = CYCLE_EVIDENCE_MAX_SCAN_RECORDS
    ) -> dict:
        """Resolve links for a bounded set of evidence under one cycle id."""

        limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
        max_scan_records = max(1, int(max_scan_records))
        merged: dict[str, Any] = {}
        evidence_ids: list[str] = []
        scanned = 0
        for record in self.store.iter_records():
            scanned += 1
            if scanned > max_scan_records:
                break
            if not record.valid:
                continue
            if record.record.get("cycle_id") != cycle_id:
                continue
            if len(evidence_ids) >= limit:
                break
            evidence_ids.append(record.record.get("evidence_id"))
            links = record.record.get("links") or {}
            if isinstance(links, Mapping):
                for key, value in links.items():
                    if value is not None and key not in merged:
                        merged[str(key)] = value
        summary, _ = sanitize_summary(merged)
        return {
            "cycle_id": cycle_id,
            "evidence_ids": evidence_ids,
            "links": summary,
        }
