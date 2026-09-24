"""Restart-safe, bounded, corruption-tolerant reader for the trading trace.

The canonical writer of the trading trace is
:mod:`backend.runtime.trading_trace` (``TradingTraceStore.safe_record``); this
module never writes, truncates, rotates or repairs the trace file.  It only
reads the durable JSONL append log, which makes existing already-written trace
events queryable after a process restart even when the in-memory
``TradingTraceStore`` tail cache is empty.

Design constraints (WORK I② P0):

* **restart-safe** — records are read from disk; no in-memory warm-up is needed.
* **no full memory load** — the file is streamed; pages, the scan budget and a
  wall-clock timeout bound every call.  The default production trace is ~33.6 GB
  and is never fully loaded.
* **bounded page size** — ``limit`` is clamped to ``max_page_size``.
* **stable cursor** — an opaque byte-offset cursor, tagged with the file
  identity (device/inode/head digest/size), lets a caller resume a page after a
  restart.  Rotation, replacement, truncation and out-of-range cursors are
  detected and surfaced, never silently followed.
* **clear ordering** — physical append order (oldest -> newest).  Forward
  pagination ascends the file, reverse pagination descends it.
* **corruption tolerant** — a malformed middle line is isolated and reported; a
  truncated final line is isolated and never repaired; a missing or empty file
  yields an empty page.
* **deterministic** — the response is a pure function of the file bytes and the
  request parameters (no wall-clock timestamps are placed in the payload).
* **redaction preserved** — only the known trace event fields are exposed and
  the ``metadata`` body is re-run through the canonical
  :func:`~backend.runtime.trading_trace.sanitize_metadata` scrubber, so a secret
  that somehow reached the file can never be re-exposed by this reader.
* **concurrent-append safe** — reads only ever observe whole complete lines; a
  line appended while a page is being read is simply not part of that page.

No sidecar index is created.  A sidecar would either require a full 33.6 GB scan
at start-up (prohibited) or introduce a second derived store that could drift
from the canonical append log.  Byte-offset cursors plus a bounded scan give
restart-safe access without any persistent index; the tail-biased reverse scan
keeps recent-trace queries inexpensive.

This module is diagnostic/read-only and carries no trading authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, Iterator, Mapping, Optional

from backend.runtime.trading_trace import (
    PARAMETER_TRADE_KEYS,
    classify_trace,
    entry_parameter_metadata,
    sanitize_metadata,
    trace_store,
)


CURSOR_VERSION = 1
READ_CHUNK_BYTES = 64 * 1024

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFAULT_MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_MAX_SCAN_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_SCAN_LINES = 200_000
MAX_MAX_SCAN_LINES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 30.0
DEFAULT_GAP_LINES = 2000

ORDERING = "APPEND_ORDER"

_DIRECTIONS = ("forward", "reverse")

# Top-level trace event fields written by ``make_event``.  Unknown top-level
# keys are dropped so an injected/legacy field can never leak through the read
# surface; the metadata body is scrubbed separately.
_EVENT_TOP_LEVEL = (
    "traceId",
    "eventId",
    "timestamp",
    "mode",
    "stage",
    "status",
    "symbol",
    "runtimeId",
    "observationId",
    "decisionId",
    "reasonCode",
)

_CYCLE_TOP_KEYS = ("cycleId", "cycle_id")
_CYCLE_META_KEYS = ("cycleId", "cycle_id", "rankingCycleId")
_TRADE_TOP_KEYS = ("tradeId", "trade_id")
_TRADE_META_KEYS = ("tradeId", "trade_id")
_CORRELATION_TOP_KEYS = ("correlationId", "correlation_id")
_CORRELATION_META_KEYS = ("correlationId", "correlation_id")


class TraceCursorError(ValueError):
    """A cursor can no longer be honoured against the current file."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    size: int
    device: int
    inode: int
    head: str

    @property
    def identity(self) -> tuple[int, int, str]:
        return (self.device, self.inode, self.head)


def _encode_cursor(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - any malformed cursor is rejected
        raise TraceCursorError("CURSOR_INVALID", "cursor is not a valid trace cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise TraceCursorError("CURSOR_INVALID", "cursor version is not supported")
    if payload.get("dir") not in _DIRECTIONS:
        raise TraceCursorError("CURSOR_INVALID", "cursor direction is invalid")
    if not isinstance(payload.get("o"), int) or payload["o"] < 0:
        raise TraceCursorError("CURSOR_INVALID", "cursor offset is invalid")
    if not isinstance(payload.get("d"), int) or not isinstance(payload.get("i"), int):
        raise TraceCursorError("CURSOR_INVALID", "cursor file identity is invalid")
    if not isinstance(payload.get("h"), str):
        raise TraceCursorError("CURSOR_INVALID", "cursor head digest is invalid")
    if not isinstance(payload.get("z"), int) or payload["z"] < 0:
        raise TraceCursorError("CURSOR_INVALID", "cursor size is invalid")
    return payload


def _coerce_timestamp(value: Any) -> Optional[float]:
    """Return an epoch-seconds float for an ISO/epoch value, or ``None``."""

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
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _record_id(record: Mapping[str, Any], top_keys, meta_keys) -> Optional[str]:
    for key in top_keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    metadata = record.get("metadata")
    if isinstance(metadata, Mapping):
        for key in meta_keys:
            value = metadata.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _record_correlation_id(record: Mapping[str, Any]) -> Optional[str]:
    explicit = _record_id(record, _CORRELATION_TOP_KEYS, _CORRELATION_META_KEYS)
    if explicit is not None:
        return explicit
    trace_id = record.get("traceId")
    return str(trace_id) if trace_id not in (None, "") else None


def _redact_record(data: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only known event fields; re-scrub the metadata body."""

    cleaned: dict[str, Any] = {}
    for key in _EVENT_TOP_LEVEL:
        if key in data:
            cleaned[key] = data[key]
    cleaned["metadata"] = sanitize_metadata(
        data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}
    )
    return cleaned


def _parse_line(raw: bytes, had_newline: bool) -> tuple[Optional[dict], Optional[str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "INVALID_ENCODING"
    stripped = text.strip()
    if not stripped:
        return None, None
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        reason = "TRUNCATED_FINAL_RECORD" if not had_newline else "INVALID_JSON"
        return None, reason
    if not isinstance(data, Mapping):
        return None, "NOT_AN_OBJECT"
    if not data:
        return None, None
    return _redact_record(data), None


class TradingTraceReader:
    """Read-only, bounded, restart-safe view over the trading trace JSONL."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        default_page_size: int = DEFAULT_PAGE_SIZE,
        max_page_size: int = MAX_PAGE_SIZE,
        max_scan_bytes: int = DEFAULT_MAX_SCAN_BYTES,
        max_scan_lines: int = DEFAULT_MAX_SCAN_LINES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        gap_lines: int = DEFAULT_GAP_LINES,
    ):
        if path is not None:
            self.path = Path(path)
        else:
            self.path = Path(trace_store.jsonl_path or "logs/runtime/trading_e2e_trace.jsonl")
        self.default_page_size = max(1, int(default_page_size))
        self.max_page_size = max(1, int(max_page_size))
        self.max_scan_bytes = max(1024, int(max_scan_bytes))
        self.max_scan_lines = max(1, int(max_scan_lines))
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.gap_lines = max(1, int(gap_lines))
        self._lock = RLock()

    # -- file identity ------------------------------------------------------

    def snapshot(self) -> FileSnapshot:
        try:
            stat = self.path.stat()
        except OSError:
            return FileSnapshot(False, 0, 0, 0, "")
        head = ""
        try:
            with self.path.open("rb") as stream:
                head = hashlib.sha256(stream.read(4096)).hexdigest()
        except OSError:
            head = ""
        return FileSnapshot(
            True,
            stat.st_size,
            int(getattr(stat, "st_dev", 0)),
            int(getattr(stat, "st_ino", 0)),
            head,
        )

    # -- low level iteration ------------------------------------------------

    def _iter_lines_forward(self, start_offset: int) -> Iterator[tuple[int, bytes, bool]]:
        with self.path.open("rb") as stream:
            stream.seek(start_offset)
            offset = start_offset
            while True:
                raw = stream.readline()
                if raw == b"":
                    return
                yield offset, raw, raw.endswith(b"\n")
                offset += len(raw)

    def _read_window(self, window_start: int, end: int) -> bytes:
        with self.path.open("rb") as stream:
            stream.seek(window_start)
            return stream.read(max(0, end - window_start))

    def _window_segments(self, window_start: int, end: int) -> list[tuple[int, bytes, bool]]:
        """Return ``(offset, raw, had_newline)`` for a bounded byte window."""

        data = self._read_window(window_start, end)
        if data == b"":
            return []
        ends_with_newline = data.endswith(b"\n")
        segments: list[tuple[int, bytes, bool]] = []
        offset = window_start
        parts = data.split(b"\n")
        last_index = len(parts) - 1
        for index, part in enumerate(parts):
            is_last = index == last_index
            if is_last and ends_with_newline:
                break
            had_newline = (not is_last) or ends_with_newline
            segments.append((offset, part, had_newline))
            offset += len(part) + 1
        return segments

    # -- cursor handling ----------------------------------------------------

    def _cursor_payload(
        self, offset: int, direction: str, snapshot: FileSnapshot
    ) -> str:
        return _encode_cursor(
            {
                "v": CURSOR_VERSION,
                "o": int(offset),
                "d": snapshot.device,
                "i": snapshot.inode,
                "h": snapshot.head,
                "z": snapshot.size,
                "dir": direction,
            }
        )

    def _resolve_cursor(
        self, cursor: Optional[str], direction: str, snapshot: FileSnapshot
    ) -> int:
        if cursor is None:
            return snapshot.size if direction == "reverse" else 0
        payload = _decode_cursor(cursor)
        if payload["dir"] != direction:
            raise TraceCursorError(
                "CURSOR_DIRECTION_MISMATCH",
                "cursor was issued for a different pagination direction",
            )
        if not snapshot.exists:
            raise TraceCursorError("FILE_MISSING", "trace file no longer exists")
        if (payload["d"], payload["i"], payload["h"]) != snapshot.identity:
            raise TraceCursorError(
                "FILE_ROTATED", "trace file was rotated or replaced after the cursor"
            )
        if snapshot.size < payload["z"]:
            raise TraceCursorError(
                "FILE_TRUNCATED", "trace file shrank after the cursor was issued"
            )
        if payload["o"] > snapshot.size:
            raise TraceCursorError(
                "CURSOR_OUT_OF_RANGE", "cursor offset is beyond the end of the file"
            )
        return payload["o"]

    # -- request normalization ---------------------------------------------

    def _normalize_limits(
        self,
        limit: Optional[int],
        max_scan_bytes: Optional[int],
        max_scan_lines: Optional[int],
        timeout_seconds: Optional[float],
    ) -> tuple[int, int, int, float]:
        try:
            normalized_limit = int(limit) if limit is not None else self.default_page_size
        except (TypeError, ValueError):
            normalized_limit = self.default_page_size
        normalized_limit = max(1, min(normalized_limit, self.max_page_size))

        try:
            normalized_bytes = (
                int(max_scan_bytes) if max_scan_bytes is not None else self.max_scan_bytes
            )
        except (TypeError, ValueError):
            normalized_bytes = self.max_scan_bytes
        normalized_bytes = max(1024, min(normalized_bytes, MAX_MAX_SCAN_BYTES))

        try:
            normalized_lines = (
                int(max_scan_lines) if max_scan_lines is not None else self.max_scan_lines
            )
        except (TypeError, ValueError):
            normalized_lines = self.max_scan_lines
        normalized_lines = max(1, min(normalized_lines, MAX_MAX_SCAN_LINES))

        try:
            normalized_timeout = (
                float(timeout_seconds)
                if timeout_seconds is not None
                else self.timeout_seconds
            )
        except (TypeError, ValueError):
            normalized_timeout = self.timeout_seconds
        normalized_timeout = max(0.0, min(normalized_timeout, MAX_TIMEOUT_SECONDS))
        return normalized_limit, normalized_bytes, normalized_lines, normalized_timeout

    def _matches(
        self,
        record: Mapping[str, Any],
        *,
        time_from: Optional[float],
        time_to: Optional[float],
        cycle_id: Optional[str],
        trade_id: Optional[str],
        correlation_id: Optional[str],
        mode: Optional[str],
        stage: Optional[str],
        reason_code: Optional[str],
        status: Optional[str],
        symbol: Optional[str],
    ) -> bool:
        if mode is not None and str(record.get("mode") or "").upper() != mode:
            return False
        if stage is not None and str(record.get("stage") or "").upper() != stage:
            return False
        if status is not None and str(record.get("status") or "").upper() != status:
            return False
        if symbol is not None and str(record.get("symbol") or "").upper() != symbol:
            return False
        if reason_code is not None:
            if str(record.get("reasonCode") or "").upper() != reason_code:
                return False
        if cycle_id is not None and _record_id(record, _CYCLE_TOP_KEYS, _CYCLE_META_KEYS) != cycle_id:
            return False
        if trade_id is not None and _record_id(record, _TRADE_TOP_KEYS, _TRADE_META_KEYS) != trade_id:
            return False
        if correlation_id is not None and _record_correlation_id(record) != correlation_id:
            return False
        if time_from is not None or time_to is not None:
            timestamp = _coerce_timestamp(record.get("timestamp"))
            if timestamp is None:
                return False
            if time_from is not None and timestamp < time_from:
                return False
            if time_to is not None and timestamp >= time_to:
                return False
        return True

    @staticmethod
    def _normalize_filter(value: Optional[str], *, upper: bool) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text.upper() if upper else text

    # -- event query --------------------------------------------------------

    def query_events(
        self,
        *,
        time_from: Any = None,
        time_to: Any = None,
        cycle_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        mode: Optional[str] = None,
        stage: Optional[str] = None,
        reason_code: Optional[str] = None,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        direction: str = "forward",
        max_scan_bytes: Optional[int] = None,
        max_scan_lines: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        """Return one bounded page of trace events, oldest -> newest by default.

        ``time_from``/``time_to`` accept ISO-8601 strings or epoch seconds; the
        window is ``[from, to)``.  ``cycle_id``/``trade_id``/``correlation_id``
        match the top-level event field or the corresponding ``metadata`` key;
        ``correlation_id`` falls back to the event ``traceId`` (the trace is the
        cross-subsystem correlation group).
        """

        normalized_direction = str(direction or "forward").strip().lower()
        if normalized_direction not in _DIRECTIONS:
            raise TraceCursorError("DIRECTION_INVALID", f"unknown direction: {direction}")

        limit_v, scan_bytes, scan_lines, timeout = self._normalize_limits(
            limit, max_scan_bytes, max_scan_lines, timeout_seconds
        )
        filters = {
            "time_from": _coerce_timestamp(time_from),
            "time_to": _coerce_timestamp(time_to),
            "cycle_id": self._normalize_filter(cycle_id, upper=False),
            "trade_id": self._normalize_filter(trade_id, upper=False),
            "correlation_id": self._normalize_filter(correlation_id, upper=False),
            "mode": self._normalize_filter(mode, upper=True),
            "stage": self._normalize_filter(stage, upper=True),
            "reason_code": self._normalize_filter(reason_code, upper=True),
            "status": self._normalize_filter(status, upper=True),
            "symbol": self._normalize_filter(symbol, upper=True),
        }

        with self._lock:
            snapshot = self.snapshot()
            if not snapshot.exists:
                return self._empty_page(
                    limit_v,
                    direction=normalized_direction,
                    reason="FILE_MISSING",
                    cursor=None,
                )
            start_offset = self._resolve_cursor(cursor, normalized_direction, snapshot)
            if normalized_direction == "reverse":
                return self._query_reverse(
                    snapshot, start_offset, limit_v, scan_bytes, scan_lines, timeout, filters
                )
            return self._query_forward(
                snapshot, start_offset, limit_v, scan_bytes, scan_lines, timeout, filters
            )

    def _empty_page(
        self, limit: int, *, direction: str, reason: str, cursor: Optional[str]
    ) -> dict[str, Any]:
        return {
            "events": [],
            "count": 0,
            "direction": direction,
            "ordering": ORDERING,
            "pagination": {"limit": limit, "nextCursor": cursor, "hasMore": False},
            "scan": {
                "partial": False,
                "reason": reason,
                "scannedLines": 0,
                "scannedBytes": 0,
                "isolatedRecords": 0,
                "truncatedFinalRecord": False,
            },
            "file": {"exists": False, "size": 0, "rotationDetected": False},
        }

    def _query_forward(
        self,
        snapshot: FileSnapshot,
        start_offset: int,
        limit: int,
        scan_bytes_budget: int,
        scan_lines_budget: int,
        timeout: float,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = monotonic() + timeout
        matched: list[dict] = []
        next_offset = start_offset
        scanned_bytes = 0
        scanned_lines = 0
        isolated = 0
        truncated_final = False
        has_more = False
        partial = False
        partial_reason: Optional[str] = None

        for offset, raw, had_newline in self._iter_lines_forward(start_offset):
            if scanned_lines >= scan_lines_budget:
                partial, partial_reason, has_more = True, "SCAN_LINE_BUDGET", True
                break
            if scanned_bytes >= scan_bytes_budget:
                partial, partial_reason, has_more = True, "SCAN_BYTE_BUDGET", True
                break
            if timeout and monotonic() > deadline:
                partial, partial_reason, has_more = True, "TIMEOUT", True
                break
            scanned_lines += 1
            scanned_bytes += len(raw)
            record, reason = _parse_line(raw, had_newline)
            if record is None:
                if reason is not None:
                    isolated += 1
                    if reason == "TRUNCATED_FINAL_RECORD":
                        truncated_final = True
                next_offset = offset + len(raw)
                continue
            if not self._matches(record, **filters):
                next_offset = offset + len(raw)
                continue
            if len(matched) >= limit:
                has_more = True
                break
            matched.append(record)
            next_offset = offset + len(raw)

        next_cursor = (
            self._cursor_payload(next_offset, "forward", snapshot)
            if (has_more or partial)
            else None
        )
        return {
            "events": matched,
            "count": len(matched),
            "direction": "forward",
            "ordering": ORDERING,
            "pagination": {
                "limit": limit,
                "nextCursor": next_cursor,
                "hasMore": has_more,
            },
            "scan": {
                "partial": partial,
                "reason": partial_reason,
                "scannedLines": scanned_lines,
                "scannedBytes": scanned_bytes,
                "isolatedRecords": isolated,
                "truncatedFinalRecord": truncated_final,
            },
            "file": {
                "exists": True,
                "size": snapshot.size,
                "rotationDetected": False,
            },
        }

    def _query_reverse(
        self,
        snapshot: FileSnapshot,
        before: int,
        limit: int,
        scan_bytes_budget: int,
        scan_lines_budget: int,
        timeout: float,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = monotonic() + timeout
        end = min(before, snapshot.size)
        window_start = max(0, end - scan_bytes_budget)
        # If the window starts inside a line, exclude that leading partial line
        # unless the preceding byte is a newline (i.e. it is a line boundary).
        leading_partial = False
        if window_start > 0:
            try:
                with self.path.open("rb") as stream:
                    stream.seek(window_start - 1)
                    leading_partial = stream.read(1) != b"\n"
            except OSError:
                leading_partial = True

        try:
            segments = self._window_segments(window_start, end)
        except OSError:
            return self._empty_page(limit, direction="reverse", reason="READ_FAILED", cursor=None)

        if leading_partial and segments:
            segments = segments[1:]

        matched: list[dict] = []
        scanned_bytes = 0
        scanned_lines = 0
        isolated = 0
        truncated_final = False
        partial = False
        partial_reason: Optional[str] = None
        last_scanned_offset = window_start
        limit_break = False

        for offset, raw, had_newline in reversed(segments):
            if scanned_lines >= scan_lines_budget:
                partial, partial_reason = True, "SCAN_LINE_BUDGET"
                break
            if scanned_bytes >= scan_bytes_budget:
                partial, partial_reason = True, "SCAN_BYTE_BUDGET"
                break
            if timeout and monotonic() > deadline:
                partial, partial_reason = True, "TIMEOUT"
                break
            if len(matched) >= limit:
                limit_break = True
                break
            scanned_lines += 1
            scanned_bytes += len(raw)
            last_scanned_offset = offset
            record, reason = _parse_line(raw, had_newline)
            if record is None:
                if reason is not None:
                    isolated += 1
                    if reason == "TRUNCATED_FINAL_RECORD":
                        truncated_final = True
                continue
            if not self._matches(record, **filters):
                continue
            matched.append(record)

        if partial:
            has_more, next_before = True, last_scanned_offset
        elif limit_break:
            has_more, next_before = True, last_scanned_offset
        elif window_start > 0:
            has_more, next_before = True, window_start
        else:
            has_more, next_before = False, None
        next_cursor = (
            self._cursor_payload(next_before, "reverse", snapshot)
            if next_before is not None
            else None
        )
        return {
            "events": matched,
            "count": len(matched),
            "direction": "reverse",
            "ordering": ORDERING,
            "pagination": {
                "limit": limit,
                "nextCursor": next_cursor,
                "hasMore": has_more,
            },
            "scan": {
                "partial": partial,
                "reason": partial_reason,
                "scannedLines": scanned_lines,
                "scannedBytes": scanned_bytes,
                "isolatedRecords": isolated,
                "truncatedFinalRecord": truncated_final,
            },
            "file": {
                "exists": True,
                "size": snapshot.size,
                "rotationDetected": False,
            },
        }

    # -- trace aggregation --------------------------------------------------

    def _collect_trace_events(
        self,
        trace_id: str,
        snapshot: FileSnapshot,
        scan_bytes_budget: int,
        scan_lines_budget: int,
        timeout: float,
    ) -> tuple[list[tuple[int, dict]], bool, bool]:
        """Collect events for one trace id scanning backward from the tail.

        Returns ``(events_with_offsets_ascending, found, partial)``.  Scanning
        stops early once the trace has been found and ``gap_lines`` consecutive
        non-matching lines have been passed (trace events are written
        contiguously for one decision cycle); otherwise it is bounded by the
        scan budget.
        """

        deadline = monotonic() + timeout
        collected: list[tuple[int, dict]] = []
        found = False
        partial = False
        gap = 0
        scanned_bytes = 0
        scanned_lines = 0
        before = snapshot.size
        window_size = min(scan_bytes_budget, READ_CHUNK_BYTES * 8) or READ_CHUNK_BYTES * 8

        while before > 0:
            if scanned_bytes >= scan_bytes_budget or scanned_lines >= scan_lines_budget:
                partial = True
                break
            if timeout and monotonic() > deadline:
                partial = True
                break
            window_start = max(0, before - window_size)
            leading_partial = False
            if window_start > 0:
                try:
                    with self.path.open("rb") as stream:
                        stream.seek(window_start - 1)
                        leading_partial = stream.read(1) != b"\n"
                except OSError:
                    partial = True
                    break
            try:
                segments = self._window_segments(window_start, before)
            except OSError:
                partial = True
                break
            if leading_partial and segments:
                segments = segments[1:]
            for offset, raw, had_newline in reversed(segments):
                if scanned_lines >= scan_lines_budget or scanned_bytes >= scan_bytes_budget:
                    partial = True
                    break
                if timeout and monotonic() > deadline:
                    partial = True
                    break
                scanned_lines += 1
                scanned_bytes += len(raw)
                record, _reason = _parse_line(raw, had_newline)
                if record is None:
                    if found:
                        gap += 1
                    continue
                if record.get("traceId") == trace_id:
                    collected.append((offset, record))
                    found = True
                    gap = 0
                elif found:
                    gap += 1
            if partial:
                break
            if found and gap >= self.gap_lines:
                break
            before = window_start

        collected.sort(key=lambda item: item[0])
        return collected, found, partial

    @staticmethod
    def _parameter_performance(
        trace_id: str,
        events: list[dict[str, Any]],
        history_event: Mapping[str, Any],
        result_event: Mapping[str, Any],
    ) -> Optional[dict[str, Any]]:
        metadata = history_event.get("metadata") or result_event.get("metadata") or {}
        linkage = {
            key: metadata.get(key)
            for key in PARAMETER_TRADE_KEYS
            if metadata.get(key) is not None
        }
        if not linkage:
            linkage = entry_parameter_metadata(events)
        if not linkage:
            return None
        return {"tradeId": metadata.get("tradeId"), "traceId": trace_id, **linkage}

    def build_trace_view(
        self, trace_id: str, events: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """Build the same read model shape as ``TradingTraceStore.trace``."""

        if not events:
            return None
        result = classify_trace(events)
        first, last = events[0], events[-1]
        result_event = next((e for e in reversed(events) if e.get("stage") == "RESULT"), {})
        execution = next((e for e in reversed(events) if e.get("stage") == "EXECUTION"), {})
        history_event = next((e for e in reversed(events) if e.get("stage") == "HISTORY"), {})
        ids: dict[str, Any] = {}
        for event in events:
            for key in ("runtimeId", "observationId", "decisionId"):
                ids[key] = event.get(key) or ids.get(key)
            metadata = event.get("metadata") or {}
            for key in ("rankingCycleId", "orderId", "exchangeOrderId", "positionId", "markerId"):
                ids[key] = metadata.get(key) or ids.get(key)
        return {
            "traceId": trace_id,
            "mode": first.get("mode"),
            "symbol": first.get("symbol"),
            "startedAt": first.get("timestamp"),
            "updatedAt": last.get("timestamp"),
            "finalDecision": (result_event.get("metadata") or {}).get("decision")
            or (first.get("metadata") or {}).get("decision"),
            "finalStatus": result["classification"],
            "primaryReason": result["primaryReason"],
            "failurePoint": result["failurePoint"],
            "executionStatus": execution.get("status"),
            "netPnL": (result_event.get("metadata") or {}).get("netPnL"),
            "parameterPerformance": self._parameter_performance(
                trace_id, events, history_event, result_event
            ),
            **ids,
            "events": events,
        }

    def get_trace(
        self,
        trace_id: str,
        *,
        max_scan_bytes: Optional[int] = None,
        max_scan_lines: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        """Return one trace read model, restart-safe, or ``None`` if absent."""

        if not isinstance(trace_id, str) or not trace_id:
            return None
        _limit, scan_bytes, scan_lines, timeout = self._normalize_limits(
            None, max_scan_bytes, max_scan_lines, timeout_seconds
        )
        with self._lock:
            snapshot = self.snapshot()
            if not snapshot.exists:
                return None
            collected, found, _partial = self._collect_trace_events(
                trace_id, snapshot, scan_bytes, scan_lines, timeout
            )
        if not found:
            return None
        events = [record for _offset, record in collected]
        return self.build_trace_view(trace_id, events)

    def recent(
        self,
        limit: int = DEFAULT_PAGE_SIZE,
        *,
        max_scan_bytes: Optional[int] = None,
        max_scan_lines: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent traces (newest first)."""

        try:
            normalized_limit = max(1, min(int(limit), self.max_page_size))
        except (TypeError, ValueError):
            normalized_limit = self.default_page_size
        _limit, scan_bytes, scan_lines, timeout = self._normalize_limits(
            normalized_limit, max_scan_bytes, max_scan_lines, timeout_seconds
        )
        with self._lock:
            snapshot = self.snapshot()
            if not snapshot.exists:
                return []
            groups, order, _partial = self._collect_recent_groups(
                normalized_limit, snapshot, scan_bytes, scan_lines, timeout
            )
        traces: list[dict[str, Any]] = []
        for trace_id in order[:normalized_limit]:
            events = [record for _offset, record in sorted(groups[trace_id])]
            view = self.build_trace_view(trace_id, events)
            if view is not None:
                traces.append(view)
        return traces

    def _collect_recent_groups(
        self,
        limit: int,
        snapshot: FileSnapshot,
        scan_bytes_budget: int,
        scan_lines_budget: int,
        timeout: float,
    ) -> tuple[dict[str, list[tuple[int, dict]]], list[str], bool]:
        deadline = monotonic() + timeout
        groups: dict[str, list[tuple[int, dict]]] = {}
        order: list[str] = []
        partial = False
        scanned_bytes = 0
        scanned_lines = 0
        before = snapshot.size
        window_size = min(scan_bytes_budget, READ_CHUNK_BYTES * 8) or READ_CHUNK_BYTES * 8

        while before > 0:
            if scanned_bytes >= scan_bytes_budget or scanned_lines >= scan_lines_budget:
                partial = True
                break
            if timeout and monotonic() > deadline:
                partial = True
                break
            window_start = max(0, before - window_size)
            leading_partial = False
            if window_start > 0:
                try:
                    with self.path.open("rb") as stream:
                        stream.seek(window_start - 1)
                        leading_partial = stream.read(1) != b"\n"
                except OSError:
                    partial = True
                    break
            try:
                segments = self._window_segments(window_start, before)
            except OSError:
                partial = True
                break
            if leading_partial and segments:
                segments = segments[1:]
            for offset, raw, had_newline in reversed(segments):
                if scanned_lines >= scan_lines_budget or scanned_bytes >= scan_bytes_budget:
                    partial = True
                    break
                if timeout and monotonic() > deadline:
                    partial = True
                    break
                scanned_lines += 1
                scanned_bytes += len(raw)
                record, _reason = _parse_line(raw, had_newline)
                if record is None:
                    continue
                trace_id = record.get("traceId")
                if not isinstance(trace_id, str) or not trace_id:
                    continue
                if trace_id not in groups:
                    groups[trace_id] = []
                    order.append(trace_id)
                groups[trace_id].append((offset, record))
            if partial:
                break
            # One extra older trace guarantees the oldest target run ended.
            if len(order) > limit:
                break
            before = window_start
        return groups, order, partial

    # -- session aggregate --------------------------------------------------

    def session(
        self,
        *,
        mode: Optional[str] = None,
        runtime_id: Optional[str] = None,
        limit: int = 200,
        max_scan_bytes: Optional[int] = None,
        max_scan_lines: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        """Reproduce ``TradingTraceStore.session`` over restart-safe reads."""

        from collections import Counter

        traces = self.recent(
            limit,
            max_scan_bytes=max_scan_bytes,
            max_scan_lines=max_scan_lines,
            timeout_seconds=timeout_seconds,
        )
        if mode:
            normalized = mode.upper()
            traces = [t for t in traces if t.get("mode") == normalized]
        if runtime_id:
            traces = [t for t in traces if t.get("runtimeId") == runtime_id]
        classifications = Counter(t["finalStatus"] for t in traces)
        reasons = Counter(t["primaryReason"] for t in traces if t.get("primaryReason"))
        events = [event for trace in traces for event in trace["events"]]
        return {
            "tradingAiMode": "OFF",
            "tradingAiStatus": "NOT_INSTALLED",
            "tradingAiRequired": False,
            "observedDecisions": len(traces),
            "strategy": dict(Counter(e["status"] for e in events if e["stage"] == "STRATEGY")),
            "ai": dict(Counter(e["status"] for e in events if e["stage"] == "AI")),
            "moneyManagement": dict(
                Counter(e["status"] for e in events if e["stage"] == "MONEY_MANAGEMENT")
            ),
            "governance": dict(
                Counter(e["status"] for e in events if e["stage"] == "GOVERNANCE")
            ),
            "executionAttempted": sum(e["stage"] == "EXECUTION" for e in events),
            "executedTrades": classifications["COMPLETE_EXECUTED"],
            "completeTraces": sum(
                v for k, v in classifications.items() if k.startswith("COMPLETE_")
            ),
            "incompleteTraces": classifications["INCOMPLETE"],
            "failedTraces": classifications["FAILED"],
            "classificationCounts": dict(classifications),
            "primaryBlockReasonCounts": dict(reasons),
        }


def default_trading_trace_reader() -> TradingTraceReader:
    return TradingTraceReader()
