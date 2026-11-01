"""Read-only knowledge reader.

Opening a reader never creates or migrates a database. A missing file,
an uninitialized file, and a failed query stay distinct from an empty hit
list. Search text is not a system instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from .knowledge_search import _snippet, compile_match


@dataclass(frozen=True)
class ReaderLimits:
    max_query_length: int = 200
    max_results: int = 8
    max_offset: int = 1_000
    max_snippet_length: int = 240
    busy_timeout_ms: int = 2_000
    max_query_seconds: float = 2.0


@dataclass(frozen=True)
class RequestContext:
    """Trusted caller scope. Query text cannot set this value."""

    caller_scope: str
    caller_id: str = "trusted-path"


@dataclass(frozen=True)
class ReaderFilters:
    source_type: str | None = None
    record_type: str | None = None
    workstream: str | None = None
    branch: str | None = None
    worktree: str | None = None
    commit_sha: str | None = None
    source_account: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    verification_state: str | None = None
    authority_scope: str | None = None
    freshness: str | None = None
    presence: str | None = None
    time_from: str | None = None
    time_to: str | None = None
    requested_access: str | None = None
    phrase: bool = False


@dataclass(frozen=True)
class ReaderHit:
    record_id: str
    title: str
    snippet: str
    source_type: str
    source_identifier: str
    relative_path: str | None
    commit_sha: str | None
    branch: str | None
    worktree: str | None
    source_timestamp: str | None
    collected_at: str
    indexed_at: str
    verification_state: str
    authority_scope: str
    freshness_state: str
    score: float
    truth_kind: str
    presence: str
    source_account: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "title": self.title,
            "snippet": self.snippet,
            "source_type": self.source_type,
            "source_identifier": self.source_identifier,
            "relative_path": self.relative_path,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "worktree": self.worktree,
            "source_timestamp": self.source_timestamp,
            "collected_at": self.collected_at,
            "indexed_at": self.indexed_at,
            "verification_state": self.verification_state,
            "authority_scope": self.authority_scope,
            "freshness_state": self.freshness_state,
            "score": self.score,
            "truth_kind": self.truth_kind,
            "presence": self.presence,
            "source_account": self.source_account,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
        }


@dataclass(frozen=True)
class ReaderResponse:
    status: str
    query: str
    results: tuple[ReaderHit, ...]
    total_count: int | None
    returned_count: int
    truncated: bool
    source_scope: str
    searched_at: str
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "query": self.query,
            "results": [hit.to_dict() for hit in self.results],
            "total_count": self.total_count,
            "returned_count": self.returned_count,
            "truncated": self.truncated,
            "source_scope": self.source_scope,
            "searched_at": self.searched_at,
            "error_code": self.error_code,
        }


_ACCESS_DENIED = "ACCESS_DENIED"
_OPERATOR = "OPERATOR"
_PUBLIC = "PUBLIC"


def _now(clock) -> str:
    moment = clock() if clock is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("TIMESTAMP_REQUIRED")
    return moment.astimezone(timezone.utc).isoformat()


def _failure(query: str, scope: str, status: str, searched_at: str, code: str | None = None) -> ReaderResponse:
    return ReaderResponse(
        status=status,
        query=query,
        results=(),
        total_count=None,
        returned_count=0,
        truncated=False,
        source_scope=scope,
        searched_at=searched_at,
        error_code=code or status,
    )


class KnowledgeReader:
    """A read-only handle. Construction is only via ``open_reader``."""

    def __init__(self, connection: sqlite3.Connection, limits: ReaderLimits) -> None:
        self._connection = connection
        self._limits = limits
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def search(
        self,
        query: str,
        *,
        request: RequestContext,
        filters: ReaderFilters | None = None,
        limit: int | None = None,
        offset: int = 0,
        clock=None,
    ) -> ReaderResponse:
        chosen = filters or ReaderFilters()
        scope = request.caller_scope
        searched_at = _now(clock)
        if scope not in {_OPERATOR, _PUBLIC, "UNAUTHENTICATED"}:
            return _failure(query, scope, _ACCESS_DENIED, searched_at)
        if chosen.requested_access == _OPERATOR and scope != _OPERATOR:
            return _failure(query, scope, _ACCESS_DENIED, searched_at, "PRIVILEGE_ESCALATION")
        try:
            match, tokens = compile_match(
                query,
                phrase=chosen.phrase,
                max_length=self._limits.max_query_length,
            )
        except Exception as exc:
            code = getattr(exc, "code", "INVALID_QUERY")
            status = "INVALID_QUERY"
            return _failure(query, scope, status, searched_at, code)
        if offset < 0 or offset > self._limits.max_offset:
            return _failure(query, scope, "INVALID_QUERY", searched_at, "OFFSET_REJECTED")
        page = self._limits.max_results if limit is None else min(limit, self._limits.max_results)
        if page < 1:
            return _failure(query, scope, "INVALID_QUERY", searched_at, "RESULT_LIMIT")
        access_sql = _access_sql(scope, chosen.requested_access)
        where = _FILTER_SQL + "\n" + access_sql
        parameters = _filter_parameters(match, chosen) 
        count_sql = f"SELECT count(*) FROM records_fts JOIN records ON records.record_id = records_fts.record_id WHERE records_fts MATCH ? {where}"
        page_sql = (
            "SELECT records.*, bm25(records_fts) AS rank "
            "FROM records_fts JOIN records ON records.record_id = records_fts.record_id "
            f"WHERE records_fts MATCH ? {where} "
            "ORDER BY rank ASC, records.record_id ASC LIMIT ? OFFSET ?"
        )
        started = time.monotonic()
        aborted = {"value": False}

        def _progress() -> int:
            if self._limits.max_query_seconds <= 0 or (
                time.monotonic() - started > self._limits.max_query_seconds
            ):
                aborted["value"] = True
                return 1
            return 0

        self._connection.set_progress_handler(_progress, 1)
        try:
            total = int(self._connection.execute(count_sql, parameters).fetchone()[0])
            rows = self._connection.execute(page_sql, parameters + (page + 1, offset)).fetchall()
        except sqlite3.OperationalError as exc:
            if aborted["value"] or _locked(exc):
                return _failure(query, scope, "TIMEOUT", searched_at)
            return _failure(query, scope, "DATABASE_ERROR", searched_at)
        except sqlite3.Error:
            return _failure(query, scope, "DATABASE_ERROR", searched_at)
        except Exception:
            return _failure(query, scope, "INTERNAL_ERROR", searched_at)
        finally:
            self._connection.set_progress_handler(None, 0)
        truncated = len(rows) > page or offset + page < total
        hits = tuple(_hit(row, tokens, self._limits.max_snippet_length) for row in rows[:page])
        status = "EMPTY" if total == 0 else "OK"
        return ReaderResponse(
            status=status,
            query=query,
            results=hits,
            total_count=total,
            returned_count=len(hits),
            truncated=truncated,
            source_scope=scope,
            searched_at=searched_at,
            error_code=None,
        )

    def get_record(
        self,
        record_id: str,
        *,
        request: RequestContext,
        clock=None,
    ) -> ReaderResponse:
        scope = request.caller_scope
        searched_at = _now(clock)
        if scope not in {_OPERATOR, _PUBLIC, "UNAUTHENTICATED"}:
            return _failure(record_id, scope, _ACCESS_DENIED, searched_at)
        try:
            row = self._connection.execute(
                "SELECT * FROM records WHERE record_id=?",
                (record_id,),
            ).fetchone()
        except sqlite3.Error:
            return _failure(record_id, scope, "DATABASE_ERROR", searched_at)
        if row is None:
            return ReaderResponse(
                status="EMPTY",
                query=record_id,
                results=(),
                total_count=0,
                returned_count=0,
                truncated=False,
                source_scope=scope,
                searched_at=searched_at,
            )
        if not _row_visible(row, scope):
            return _failure(record_id, scope, _ACCESS_DENIED, searched_at)
        hit = _hit(row, (), self._limits.max_snippet_length)
        return ReaderResponse(
            status="OK",
            query=record_id,
            results=(hit,),
            total_count=1,
            returned_count=1,
            truncated=False,
            source_scope=scope,
            searched_at=searched_at,
        )


def open_reader(path: str | Path, limits: ReaderLimits | None = None) -> tuple[KnowledgeReader | None, str | None]:
    """Open an existing store read-only.

    The status is ``NOT_AVAILABLE``, ``NOT_INITIALIZED``, or ``DATABASE_ERROR``.
    ``None`` means the reader is open. This function does not create a file
    and does not apply a migration.
    """

    bounds = limits or ReaderLimits()
    target = Path(path)
    if target.is_symlink() or not target.exists():
        return None, "NOT_AVAILABLE"
    if not target.is_file():
        return None, "NOT_AVAILABLE"
    uri = "file:" + quote(target.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=bounds.busy_timeout_ms / 1000)
    except sqlite3.Error:
        return None, "DATABASE_ERROR"
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute(f"PRAGMA busy_timeout={int(bounds.busy_timeout_ms)}")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'"
        ).fetchone()
        if version != 1 or table is None:
            connection.close()
            return None, "NOT_INITIALIZED"
    except sqlite3.Error:
        connection.close()
        return None, "DATABASE_ERROR"
    return KnowledgeReader(connection, bounds), None


_FILTER_SQL = """
          AND (? IS NULL OR records.source_type = ?)
          AND (? IS NULL OR records.record_type = ?)
          AND (? IS NULL OR records.workstream = ?)
          AND (? IS NULL OR records.branch = ?)
          AND (? IS NULL OR records.worktree = ?)
          AND (? IS NULL OR records.commit_sha = ?)
          AND (? IS NULL OR records.source_account = ?)
          AND (? IS NULL OR records.conversation_id = ?)
          AND (? IS NULL OR records.message_id = ?)
          AND (? IS NULL OR records.verification_state = ?)
          AND (? IS NULL OR records.authority_scope = ?)
          AND (? IS NULL OR records.freshness = ?)
          AND (? IS NULL OR records.presence = ?)
          AND (? IS NULL OR COALESCE(records.source_timestamp, records.collected_at) >= ?)
          AND (? IS NULL OR COALESCE(records.source_timestamp, records.collected_at) <= ?)
"""


def _filter_parameters(match: str, filters: ReaderFilters) -> tuple[object, ...]:
    return (
        match,
        filters.source_type,
        filters.source_type,
        filters.record_type,
        filters.record_type,
        filters.workstream,
        filters.workstream,
        filters.branch,
        filters.branch,
        filters.worktree,
        filters.worktree,
        filters.commit_sha,
        filters.commit_sha,
        filters.source_account,
        filters.source_account,
        filters.conversation_id,
        filters.conversation_id,
        filters.message_id,
        filters.message_id,
        filters.verification_state,
        filters.verification_state,
        filters.authority_scope,
        filters.authority_scope,
        filters.freshness,
        filters.freshness,
        filters.presence,
        filters.presence,
        filters.time_from,
        filters.time_from,
        filters.time_to,
        filters.time_to,
    )


def _access_sql(caller: str, requested: str | None) -> str:
    if caller == _OPERATOR and requested == _PUBLIC:
        return "AND json_extract(records.metadata_json, '$.access_scope') = 'PUBLIC'"
    if caller == _OPERATOR and requested == _OPERATOR:
        return (
            "AND (json_extract(records.metadata_json, '$.access_scope') IS NULL "
            "OR json_extract(records.metadata_json, '$.access_scope') = 'OPERATOR')"
        )
    if caller == _OPERATOR:
        return (
            "AND (json_extract(records.metadata_json, '$.access_scope') IS NULL "
            "OR json_extract(records.metadata_json, '$.access_scope') IN ('PUBLIC', 'OPERATOR'))"
        )
    return "AND json_extract(records.metadata_json, '$.access_scope') = 'PUBLIC'"


def _row_visible(row: sqlite3.Row, caller: str) -> bool:
    import json

    try:
        metadata = json.loads(row["metadata_json"])
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    access = metadata.get("access_scope")
    if caller == _OPERATOR:
        return access in {None, _PUBLIC, _OPERATOR}
    return access == _PUBLIC


def _hit(row: sqlite3.Row, tokens: tuple[str, ...], limit: int) -> ReaderHit:
    rank = row["rank"] if "rank" in row.keys() else 0.0
    return ReaderHit(
        record_id=row["record_id"],
        title=row["title"],
        snippet=_snippet(row["content"], tokens, limit),
        source_type=row["source_type"],
        source_identifier=row["source_identifier"],
        relative_path=row["relative_path"],
        commit_sha=row["commit_sha"],
        branch=row["branch"],
        worktree=row["worktree"],
        source_timestamp=row["source_timestamp"],
        collected_at=row["collected_at"],
        indexed_at=row["indexed_at"],
        verification_state=row["verification_state"],
        authority_scope=row["authority_scope"],
        freshness_state=row["freshness"],
        score=round(-float(rank), 6),
        truth_kind=row["truth_kind"],
        presence=row["presence"],
        source_account=row["source_account"],
        conversation_id=row["conversation_id"],
        message_id=row["message_id"],
    )


def _locked(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return "locked" in text or "busy" in text or "interrupt" in text or "aborted" in text
