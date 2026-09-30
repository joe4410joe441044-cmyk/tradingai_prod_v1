"""Dedicated append-only monitoring-state journal with bounded recovery.

Persistence authority decision (Phase 2): a **new** dedicated JSONL journal,
reusing the *pattern* of :mod:`backend.runtime.cycle_evidence_store` (explicit
path, deterministic event ID, idempotent append, conflict detection, process
local lock, fsync, tail isolation) but **not** its destination and **not** the
Supervisor conversation/audit SQLite authority.

Safety properties:

- the constructor requires an explicit path; there is no default, no
  environment-derived path and no import-time or constructor-time I/O;
- routine updates are append-only: the whole file is never rewritten;
- record size and recovery work are bounded;
- corruption is isolated and reported, never silently repaired or deleted.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock, RLock

from .monitoring_state_models import (
    CorruptRecord, RecoveryResult, SCHEMA_VERSION, StateEvent,
)

DEFAULT_MAX_RECORD_BYTES = 65536
DEFAULT_MAX_RECOVERY_RECORDS = 50000
DEFAULT_MAX_RECOVERY_BYTES = 8 * 1024 * 1024

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
    WRITTEN = "WRITTEN"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AppendResult:
    outcome: AppendOutcome
    event_id: str | None = None
    error: str | None = None

    @property
    def written(self) -> bool:
        return self.outcome is AppendOutcome.WRITTEN

    @property
    def idempotent(self) -> bool:
        return self.outcome is AppendOutcome.DUPLICATE


class MonitoringStateStore:
    """Append-only, idempotent, restart-safe monitoring-state journal."""

    def __init__(self, path, *, max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
                 max_recovery_records: int = DEFAULT_MAX_RECOVERY_RECORDS,
                 max_recovery_bytes: int = DEFAULT_MAX_RECOVERY_BYTES, fsync: bool = True,
                 schema_version: str = SCHEMA_VERSION):
        if path is None or isinstance(path, bool):
            raise TypeError("an explicit monitoring-state journal path is required")
        if not 1 <= max_record_bytes <= 10**7:
            raise ValueError("record byte bound out of range")
        if max_recovery_records < 1 or max_recovery_bytes < 1:
            raise ValueError("recovery bounds must be positive")
        self.path = Path(path)
        self.max_record_bytes = max_record_bytes
        self.max_recovery_records = max_recovery_records
        self.max_recovery_bytes = max_recovery_bytes
        self.fsync = fsync
        self.schema_version = schema_version
        self.persist_errors = 0
        self._lock = RLock()
        self._index: dict[str, str] | None = None
        self._indexed_size: int | None = None

    # -- reading ------------------------------------------------------------

    def _current_size(self) -> int | None:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def _physical_lines(self):
        """Bounded physical lines plus (byte_bounded, terminated) flags."""

        size = self._current_size() or 0
        byte_bounded = size > self.max_recovery_bytes
        with self.path.open("rb") as stream:
            blob = stream.read(self.max_recovery_bytes)
        terminated = blob == b"" or blob.endswith(b"\n")
        parts = blob.split(b"\n")
        lines: list[tuple[int, bytes]] = []
        for offset, raw in enumerate(parts):
            if offset == len(parts) - 1 and not terminated:
                lines.append((offset + 1, raw))  # possible truncated tail
            elif raw:
                lines.append((offset + 1, raw))
        return lines, byte_bounded, terminated

    @staticmethod
    def _parse(raw: bytes, schema_version: str) -> tuple[StateEvent | None, str | None]:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, "INVALID_ENCODING"
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None, "INVALID_JSON"
        if not isinstance(data, dict):
            return None, "NOT_AN_OBJECT"
        if data.get("schema_version") != schema_version:
            return None, "SCHEMA_VERSION_UNSUPPORTED"
        data.pop("event_id", None)  # computed output, never caller input
        try:
            return StateEvent.model_validate(data), None
        except Exception:
            return None, "INVALID_RECORD"

    def _scan(self):
        """One bounded pass: returns (event_index, RecoveryResult, latest_states)."""

        index: dict[str, str] = {}
        states: dict[str, StateEvent] = {}
        corrupted: list[CorruptRecord] = []
        warnings: set[str] = set()
        records = 0
        bytes_read = 0
        duplicates = 0
        partial = False
        if not self.path.exists():
            return index, RecoveryResult(exists=False), states
        lines, byte_bounded, terminated = self._physical_lines()
        if byte_bounded:
            partial = True
            warnings.add("RECOVERY_BYTE_BUDGET")
        final_position = lines[-1][0] if lines else 0
        for position, raw in lines:
            if records >= self.max_recovery_records:
                partial = True
                warnings.add("RECOVERY_RECORD_BUDGET")
                break
            records += 1
            bytes_read += len(raw) + 1
            if len(raw) > self.max_record_bytes:
                corrupted.append(CorruptRecord(position=position, reason="OVERSIZED_RECORD"))
                continue
            if not raw.strip():
                continue
            event, reason = self._parse(raw, self.schema_version)
            if event is None and reason == "INVALID_JSON" and position == final_position and not terminated:
                reason = "TRUNCATED_FINAL_RECORD"
            if event is None:
                corrupted.append(CorruptRecord(position=position, reason=reason))
                continue
            if event.event_id in index:
                duplicates += 1
                continue
            index[event.event_id] = event.content_digest()
            states[event.fingerprint] = event
        recovery = RecoveryResult(
            states=tuple(sorted((e.state for e in states.values()), key=lambda s: s.fingerprint)),
            event_ids=tuple(index), records_read=records, bytes_read=bytes_read,
            corruption_count=len(corrupted), duplicate_events=duplicates, partial=partial,
            exists=True, warnings=tuple(warnings), corrupted=tuple(corrupted),
        )
        return index, recovery, states

    def recover(self) -> RecoveryResult:
        """Rebuild the latest state per fingerprint with bounded, streaming work."""

        return self._scan()[1]

    def load_states(self):
        return self.recover().states

    def _ensure_index(self) -> dict[str, str]:
        if self._index is not None and self._indexed_size == self._current_size():
            return self._index
        index, _, _ = self._scan()
        self._index = index
        self._indexed_size = self._current_size()
        return index

    # -- writing ------------------------------------------------------------

    def append(self, event) -> AppendResult:
        """Append one event idempotently; never raises for a data problem."""

        if isinstance(event, dict):
            payload = dict(event)
            if payload.get("schema_version") != self.schema_version:
                return AppendResult(AppendOutcome.REJECTED, error="SCHEMA_VERSION_UNSUPPORTED")
            payload.pop("event_id", None)
            try:
                event = StateEvent.model_validate(payload)
            except Exception:
                return AppendResult(AppendOutcome.REJECTED, error="INVALID_RECORD")
        if not isinstance(event, StateEvent):
            return AppendResult(AppendOutcome.REJECTED, error="INVALID_RECORD")
        if event.schema_version != self.schema_version:
            return AppendResult(AppendOutcome.REJECTED, error="SCHEMA_VERSION_UNSUPPORTED")
        line = event.stable_json()
        if len(line.encode("utf-8")) > self.max_record_bytes:
            return AppendResult(AppendOutcome.REJECTED, event_id=event.event_id,
                                error="OVERSIZED_RECORD")
        digest = event.content_digest()
        with self._lock, _path_lock(self.path):
            index = self._ensure_index()
            existing = index.get(event.event_id)
            if existing is not None:
                if existing == digest:
                    return AppendResult(AppendOutcome.DUPLICATE, event_id=event.event_id)
                return AppendResult(AppendOutcome.CONFLICT, event_id=event.event_id,
                                    error="conflicting content for deterministic event_id")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                try:
                    os.write(fd, (line + "\n").encode("utf-8"))
                    if self.fsync:
                        os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError as error:
                self.persist_errors += 1
                return AppendResult(AppendOutcome.REJECTED, event_id=event.event_id,
                                    error=str(error))
            index[event.event_id] = digest
            self._indexed_size = self._current_size()
            return AppendResult(AppendOutcome.WRITTEN, event_id=event.event_id)

    def append_many(self, events):
        return [self.append(event) for event in events]
