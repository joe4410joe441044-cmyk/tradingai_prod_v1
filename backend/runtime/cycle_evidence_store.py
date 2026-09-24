"""Durable, append-only, restart-safe store for canonical evidence envelopes.

This is the persistence foundation for the WORK I canonical cycle evidence
envelope.  Store-role contract (contract § I):

- it stores ONLY the observational evidence envelope defined in
  :mod:`backend.runtime.cycle_evidence`;
- it does **not** duplicate any existing canonical store.  It is not a second
  trade-history store, a second parameter-performance store or a second
  parameter-revision store.  Trade facts continue to live in Stage 13, stage
  observations in the trading trace and revisions in the parameter archive; an
  envelope references them by id through its ``links`` / ``source_record_id``;
- it is append-only: records are never updated or deleted in place;
- it is idempotent: appending the same logical envelope twice is a no-op;
- conflicting content for the same deterministic ``evidence_id`` fails closed;
- reads are restart-safe, streaming and bounded, and a corrupt/short line is
  isolated (reported, never silently repaired);
- it discovers the CWD-relative default only through an explicit path, so
  tests can always point it at a temporary directory.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Iterator, Mapping, Optional

from backend.runtime.cycle_evidence import (
    CycleEvidenceError,
    EvidenceEnvelope,
    IntegrityError,
    validate_envelope,
)

CYCLE_EVIDENCE_PATH_ENV = "CYCLE_EVIDENCE_PATH"
DEFAULT_CYCLE_EVIDENCE_PATH = "logs/runtime/cycle_evidence.jsonl"
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 500

_PATH_LOCKS: dict[str, RLock] = {}
_PATH_LOCKS_GUARD = Lock()


def _path_lock(path: Path) -> RLock:
    key = str(path.resolve()) if path.exists() else str(path.absolute())
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _PATH_LOCKS[key] = lock
        return lock


class AppendOutcome(str, Enum):
    """Outcome of one append attempt."""

    WRITTEN = "WRITTEN"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AppendResult:
    """Result of one append attempt (never raises for a data problem)."""

    outcome: AppendOutcome
    evidence_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def written(self) -> bool:
        return self.outcome is AppendOutcome.WRITTEN

    @property
    def idempotent(self) -> bool:
        return self.outcome is AppendOutcome.DUPLICATE


@dataclass(frozen=True)
class RecordRead:
    """One physical line read result (valid or isolated)."""

    position: int
    record: Optional[dict]
    reason: Optional[str] = None

    @property
    def valid(self) -> bool:
        return self.record is not None


def _encode_cursor(position: int) -> str:
    return base64.urlsafe_b64encode(str(position).encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> int:
    try:
        padded = value + "=" * (-len(value) % 4)
        return int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
    except Exception as exc:  # noqa: BLE001 - any malformed cursor is invalid
        raise ValueError("invalid cursor") from exc


class CycleEvidenceStore:
    """Append-only, idempotent, restart-safe envelope store."""

    def __init__(self, path: Optional[Path] = None, *, max_query_limit: int = MAX_QUERY_LIMIT):
        self.path = Path(path) if path is not None else Path(
            os.environ.get(CYCLE_EVIDENCE_PATH_ENV, DEFAULT_CYCLE_EVIDENCE_PATH)
        )
        self.max_query_limit = max(1, int(max_query_limit))
        self.persist_errors = 0
        self._lock = RLock()
        self._index: Optional[dict[str, str]] = None
        self._indexed_size: Optional[int] = None

    # -- reading ------------------------------------------------------------

    def _iter_lines(self) -> Iterator[tuple[int, str, bool]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as stream:
            position = 0
            while True:
                raw = stream.readline()
                if raw == "":
                    break
                position += 1
                yield position, raw, raw.endswith("\n")

    def _parse_line(self, raw: str, had_newline: bool) -> tuple[Optional[dict], Optional[str]]:
        stripped = raw.strip()
        if not stripped:
            return None, None
        try:
            data = json.loads(stripped)
        except (ValueError, TypeError):
            reason = "TRUNCATED_FINAL_RECORD" if not had_newline else "INVALID_JSON"
            return None, reason
        if not isinstance(data, Mapping):
            return None, "NOT_AN_OBJECT"
        try:
            envelope = EvidenceEnvelope.from_dict(data)
        except IntegrityError:
            return None, "INTEGRITY_MISMATCH"
        except (CycleEvidenceError, ValueError, TypeError, KeyError):
            return None, "INVALID_RECORD"
        return envelope.to_dict(), None

    def iter_records(self, *, limit: Optional[int] = None) -> Iterator[RecordRead]:
        """Stream physical records; corrupt/truncated lines are isolated."""

        emitted = 0
        for position, raw, had_newline in self._iter_lines():
            record, reason = self._parse_line(raw, had_newline)
            if limit is not None and emitted >= limit:
                return
            if record is None and reason is None:
                continue
            if record is None:
                yield RecordRead(position=position, record=None, reason=reason)
                continue
            emitted += 1
            yield RecordRead(position=position, record=record, reason=None)

    def load(self) -> list[dict]:
        """Return all valid envelopes (streaming; corrupt lines skipped)."""

        return [item.record for item in self.iter_records() if item.valid]

    def corruption_report(self) -> list[dict]:
        """Return isolated (corrupt/truncated) records with a reason."""

        return [
            {"position": item.position, "reason": item.reason}
            for item in self.iter_records()
            if not item.valid and item.reason is not None
        ]

    def get(self, evidence_id: Any) -> Optional[dict]:
        if not isinstance(evidence_id, str) or not evidence_id:
            return None
        for item in self.iter_records():
            if item.valid and item.record.get("evidence_id") == evidence_id:
                return item.record
        return None

    def query(
        self,
        *,
        cycle_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        evidence_type: Optional[str] = None,
        lifecycle_stage: Optional[int] = None,
        mode: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        cursor: Optional[str] = None,
    ) -> dict:
        """Bounded, cursor-paginated read (oldest → newest file order)."""

        try:
            normalized_limit = max(1, min(int(limit), self.max_query_limit))
        except (TypeError, ValueError):
            normalized_limit = DEFAULT_QUERY_LIMIT
        start_after = 0
        if cursor is not None:
            start_after = _decode_cursor(cursor)
        normalized_mode = mode.strip().upper() if isinstance(mode, str) else None
        normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else None
        normalized_type = (
            str(evidence_type).strip().upper() if evidence_type is not None else None
        )

        records: list[dict] = []
        last_position = start_after
        has_more = False
        for item in self.iter_records():
            if item.position <= start_after:
                continue
            if not item.valid:
                continue
            record = item.record
            if cycle_id is not None and record.get("cycle_id") != cycle_id:
                continue
            if trade_id is not None and record.get("trade_id") != trade_id:
                continue
            if correlation_id is not None and record.get("correlation_id") != correlation_id:
                continue
            if normalized_type is not None and record.get("evidence_type") != normalized_type:
                continue
            if lifecycle_stage is not None and record.get("lifecycle_stage") != lifecycle_stage:
                continue
            if normalized_mode is not None and record.get("mode") != normalized_mode:
                continue
            if normalized_symbol is not None and str(
                record.get("symbol") or ""
            ).upper() != normalized_symbol:
                continue
            if len(records) >= normalized_limit:
                has_more = True
                break
            records.append(record)
            last_position = item.position
        next_cursor = _encode_cursor(last_position) if has_more else None
        return {
            "records": records,
            "count": len(records),
            "pagination": {
                "limit": normalized_limit,
                "nextCursor": next_cursor,
                "hasMore": has_more,
            },
        }

    # -- writing ------------------------------------------------------------

    def _ensure_index(self) -> dict[str, str]:
        if self._index is not None:
            return self._index
        index: dict[str, str] = {}
        for item in self.iter_records():
            if not item.valid:
                continue
            record = item.record
            evidence_id = record.get("evidence_id")
            if not isinstance(evidence_id, str):
                continue
            if evidence_id in index:
                continue
            logical = dict(record)
            logical.pop("recorded_at", None)
            logical.pop("integrity", None)
            index[evidence_id] = json.dumps(
                logical, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            )
        self._index = index
        self._indexed_size = self._current_size()
        return index

    def _current_size(self) -> Optional[int]:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    @staticmethod
    def _logical_fingerprint(envelope: EvidenceEnvelope) -> str:
        body = envelope.body(include_recorded_at=False)
        return json.dumps(
            body, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        )

    def append(self, envelope: Any) -> AppendResult:
        """Append one envelope idempotently; never raises for a data problem."""

        try:
            validated = validate_envelope(envelope)
        except (CycleEvidenceError, ValueError, TypeError) as exc:
            return AppendResult(AppendOutcome.REJECTED, error=str(exc))
        evidence_id = validated.evidence_id
        fingerprint = self._logical_fingerprint(validated)
        with self._lock, _path_lock(self.path):
            if self._index is not None and self._indexed_size != self._current_size():
                self._index = None
            index = self._ensure_index()
            existing = index.get(evidence_id)
            if existing is not None:
                if existing == fingerprint:
                    return AppendResult(AppendOutcome.DUPLICATE, evidence_id=evidence_id)
                return AppendResult(
                    AppendOutcome.CONFLICT,
                    evidence_id=evidence_id,
                    error="conflicting content for deterministic evidence_id",
                )
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                line = validated.to_json()
                fd = os.open(
                    self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600
                )
                try:
                    os.write(fd, (line + "\n").encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except (OSError, TypeError, ValueError) as exc:
                self.persist_errors += 1
                return AppendResult(
                    AppendOutcome.REJECTED, evidence_id=evidence_id, error=str(exc)
                )
            index[evidence_id] = fingerprint
            self._indexed_size = self._current_size()
            return AppendResult(AppendOutcome.WRITTEN, evidence_id=evidence_id)

    def append_many(self, envelopes) -> list[AppendResult]:
        return [self.append(envelope) for envelope in envelopes]


def default_cycle_evidence_store() -> CycleEvidenceStore:
    return CycleEvidenceStore()
