"""SQLite knowledge store.

Importing this module does not create a database. A path is required for
``create`` and ``open``. There is no production default path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import sqlite3
import time
from typing import Any, Callable, Mapping

from .security import secret_bytes, secret_filename


STORE_SCHEMA_VERSION = "tradingai-knowledge-store/v1"
ALLOWED_TRUTH = frozenset(
    {
        "SOURCE_TRUTH",
        "PROJECT_TRUTH",
        "HISTORICAL_CONTEXT",
        "AGENT_REPORTED",
        "GIT_VERIFIED",
        "UNKNOWN",
    }
)
FORBIDDEN_TRUTH = frozenset({"RUNTIME_VERIFIED", "EXCHANGE_VERIFIED"})


class StoreError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StoreLimits:
    max_record_bytes: int = 262_144
    max_batch_size: int = 200
    max_results: int = 20
    max_query_length: int = 200
    max_snippet_length: int = 240
    max_transaction_seconds: float = 5.0
    busy_timeout_ms: int = 2_000
    max_offset: int = 1_000


@dataclass(frozen=True)
class StoreItem:
    source_type: str
    source_identifier: str
    record_type: str
    title: str
    content: str
    collected_at: str
    verification_state: str
    truth_kind: str
    content_hash: str | None = None
    relative_path: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    worktree: str | None = None
    reported_at: str | None = None
    observed_at: str | None = None
    source_timestamp: str | None = None
    source_account: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    workstream: str | None = None
    metadata: Mapping[str, str] | None = None


@dataclass(frozen=True)
class SyncResult:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    missing: int = 0
    rejected: int = 0
    error: str | None = None
    rejected_codes: tuple[str, ...] = field(default_factory=tuple)


def logical_key(item: StoreItem) -> str:
    payload = json.dumps(
        [
            item.source_type,
            item.source_identifier,
            item.record_type,
            item.worktree or "",
            item.relative_path or "",
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def version_id(item: StoreItem, content_hash: str) -> str:
    payload = json.dumps(
        [logical_key(item), content_hash, item.commit_sha or ""],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _connect(path: Path, limits: StoreLimits) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=limits.busy_timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout={int(limits.busy_timeout_ms)}")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _apply_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY,
            record_id TEXT NOT NULL UNIQUE,
            logical_key TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_identifier TEXT NOT NULL,
            record_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            verification_state TEXT NOT NULL,
            authority_scope TEXT NOT NULL,
            truth_kind TEXT NOT NULL,
            freshness TEXT NOT NULL,
            presence TEXT NOT NULL,
            relative_path TEXT,
            commit_sha TEXT,
            branch TEXT,
            worktree TEXT,
            reported_at TEXT,
            observed_at TEXT,
            source_timestamp TEXT,
            source_account TEXT,
            conversation_id TEXT,
            message_id TEXT,
            workstream TEXT,
            superseded_by TEXT,
            scan_scope TEXT,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_records_logical ON records(logical_key);
        CREATE INDEX IF NOT EXISTS idx_records_scope ON records(scan_scope, presence);
        CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
            record_id UNINDEXED,
            title,
            content
        );
        """
    )
    connection.execute("PRAGMA user_version=1")


class KnowledgeStore:
    def __init__(self, connection: sqlite3.Connection, limits: StoreLimits) -> None:
        self._connection = connection
        self._limits = limits
        self._depth = 0
        self._closed = False

    @classmethod
    def create(cls, path: str | Path, limits: StoreLimits | None = None) -> "KnowledgeStore":
        if path is None or path == "":
            raise StoreError("PATH_REQUIRED")
        target = Path(path)
        bounds = limits or StoreLimits()
        try:
            connection = _connect(target, bounds)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                connection.close()
                raise StoreError("SCHEMA_MISMATCH")
            _apply_schema(connection)
            connection.commit()
        except StoreError:
            raise
        except sqlite3.Error:
            raise StoreError("DATABASE_ERROR") from None
        return cls(connection, bounds)

    @classmethod
    def open(cls, path: str | Path, limits: StoreLimits | None = None) -> "KnowledgeStore":
        if path is None or path == "":
            raise StoreError("PATH_REQUIRED")
        target = Path(path)
        if not target.is_file():
            raise StoreError("STORE_NOT_FOUND")
        bounds = limits or StoreLimits()
        try:
            connection = _connect(target, bounds)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                connection.close()
                raise StoreError("SCHEMA_MISMATCH")
        except StoreError:
            raise
        except sqlite3.Error:
            raise StoreError("DATABASE_ERROR") from None
        return cls(connection, bounds)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def integrity_check(self) -> str:
        self._require_open()
        row = self._connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise StoreError("INTEGRITY_FAILED")
        return "OK"

    def schema_version(self) -> str:
        self._require_open()
        return STORE_SCHEMA_VERSION

    def in_transaction(self, action: Callable[[], Any]) -> Any:
        self._require_open()
        self._begin()
        try:
            result = action()
        except Exception:
            self._rollback()
            raise
        self._commit()
        return result

    def upsert(self, item: StoreItem, *, indexed_at: str, scan_scope: str) -> str:
        outcome = self.in_transaction(
            lambda: self._upsert(item, indexed_at=indexed_at, scan_scope=scan_scope, seen=None)
        )
        return outcome

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        self._require_open()
        row = self._connection.execute(
            "SELECT * FROM records WHERE record_id=?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return _public_row(row)

    def list_records(self, *, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        self._require_open()
        bounded = self._limits.max_results if limit is None else min(limit, self._limits.max_results)
        if bounded < 1:
            raise StoreError("RESULT_LIMIT")
        rows = self._connection.execute(
            "SELECT * FROM records ORDER BY record_id ASC LIMIT ?",
            (bounded,),
        ).fetchall()
        return tuple(_public_row(row) for row in rows)

    def delete_record(self, record_id: str) -> bool:
        def action() -> bool:
            row = self._connection.execute(
                "SELECT id, title, content FROM records WHERE record_id=?",
                (record_id,),
            ).fetchone()
            if row is None:
                return False
            self._connection.execute("DELETE FROM records WHERE record_id=?", (record_id,))
            self._connection.execute("DELETE FROM records_fts WHERE rowid=?", (row["id"],))
            return True

        return bool(self.in_transaction(action))

    def sync(
        self,
        items: tuple[StoreItem, ...] | list[StoreItem],
        *,
        indexed_at: str,
        scan_scope: str,
        complete: bool,
        time_fn: Callable[[], float] | None = None,
    ) -> SyncResult:
        self._require_open()
        if not indexed_at:
            return SyncResult(error="TIMESTAMP_REQUIRED")
        if len(items) > self._limits.max_batch_size:
            return SyncResult(error="BATCH_TOO_LARGE")
        clock = time_fn or time.monotonic
        started = clock()
        rejected: list[str] = []
        inserted = skipped = superseded = 0
        seen: list[str] = []
        try:
            self._begin()
            for item in items:
                if clock() - started > self._limits.max_transaction_seconds:
                    raise StoreError("TRANSACTION_TIMEOUT")
                try:
                    state = self._upsert(item, indexed_at=indexed_at, scan_scope=scan_scope, seen=seen)
                except StoreError as exc:
                    if exc.code in {"SECRET_EXCLUDED", "RECORD_INVALID", "OVERSIZED", "UNPROVEN_AUTHORITY"}:
                        rejected.append(exc.code)
                        continue
                    raise
                if state == "SKIPPED":
                    skipped += 1
                elif state == "INSERTED":
                    inserted += 1
                else:
                    inserted += 1
                    superseded += 1
            missing = 0
            if complete:
                missing = self._mark_missing(scan_scope, seen)
            self._commit()
        except StoreError as exc:
            self._rollback()
            return SyncResult(error=exc.code, rejected_codes=tuple(rejected))
        except sqlite3.Error:
            self._rollback()
            return SyncResult(error="DATABASE_ERROR")
        return SyncResult(
            inserted=inserted,
            skipped=skipped,
            superseded=superseded,
            missing=missing,
            rejected=len(rejected),
            rejected_codes=tuple(rejected),
        )

    def _upsert(
        self,
        item: StoreItem,
        *,
        indexed_at: str,
        scan_scope: str,
        seen: list[str] | None,
    ) -> str:
        prepared = _prepare(item, self._limits)
        key = prepared["logical_key"]
        if seen is not None:
            seen.append(key)
        existing = self._connection.execute(
            "SELECT record_id FROM records WHERE record_id=?",
            (prepared["record_id"],),
        ).fetchone()
        if existing is not None:
            self._connection.execute(
                "UPDATE records SET last_seen_at=?, scan_scope=? WHERE record_id=?",
                (indexed_at, scan_scope, prepared["record_id"]),
            )
            return "SKIPPED"
        presence, freshness = _presence_for(item.record_type)
        replaced = 0
        if presence == "CURRENT":
            replaced = self._connection.execute(
                """
                UPDATE records
                SET presence='HISTORICAL', freshness='HISTORICAL', superseded_by=?
                WHERE logical_key=? AND presence='CURRENT'
                """,
                (prepared["record_id"], key),
            ).rowcount
        self._connection.execute(
            """
            INSERT INTO records (
                record_id, logical_key, schema_version, source_type, source_identifier,
                record_type, title, content, content_hash, collected_at, indexed_at,
                last_seen_at, verification_state, authority_scope, truth_kind, freshness,
                presence, relative_path, commit_sha, branch, worktree, reported_at,
                observed_at, source_timestamp, source_account, conversation_id, message_id,
                workstream, superseded_by, scan_scope, metadata_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?
            )
            """,
            (
                prepared["record_id"],
                key,
                STORE_SCHEMA_VERSION,
                item.source_type,
                item.source_identifier,
                item.record_type,
                prepared["title"],
                prepared["content"],
                prepared["content_hash"],
                item.collected_at,
                indexed_at,
                indexed_at,
                prepared["verification_state"],
                "NONE",
                prepared["truth_kind"],
                freshness,
                presence,
                item.relative_path,
                item.commit_sha,
                item.branch,
                item.worktree,
                item.reported_at,
                item.observed_at,
                item.source_timestamp,
                item.source_account,
                item.conversation_id,
                item.message_id,
                item.workstream,
                scan_scope,
                prepared["metadata_json"],
            ),
        )
        row_id = self._connection.execute(
            "SELECT id FROM records WHERE record_id=?",
            (prepared["record_id"],),
        ).fetchone()[0]
        self._connection.execute(
            "INSERT INTO records_fts(rowid, record_id, title, content) VALUES (?, ?, ?, ?)",
            (row_id, prepared["record_id"], prepared["title"], prepared["content"]),
        )
        return "SUPERSEDED" if replaced else "INSERTED"

    def _mark_missing(self, scan_scope: str, seen: list[str]) -> int:
        self._connection.execute("CREATE TEMP TABLE IF NOT EXISTS seen_keys(logical_key TEXT PRIMARY KEY)")
        self._connection.execute("DELETE FROM seen_keys")
        self._connection.executemany(
            "INSERT OR IGNORE INTO seen_keys(logical_key) VALUES (?)",
            [(key,) for key in seen],
        )
        cursor = self._connection.execute(
            """
            UPDATE records
            SET presence='MISSING', freshness='UNKNOWN'
            WHERE scan_scope=? AND presence='CURRENT'
              AND logical_key NOT IN (SELECT logical_key FROM seen_keys)
            """,
            (scan_scope,),
        )
        return int(cursor.rowcount)

    def _begin(self) -> None:
        if self._depth == 0:
            self._connection.execute("BEGIN IMMEDIATE")
        self._depth += 1

    def _commit(self) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._connection.commit()

    def _rollback(self) -> None:
        self._depth = 0
        try:
            self._connection.rollback()
        except sqlite3.Error:
            return

    def _require_open(self) -> None:
        if self._closed:
            raise StoreError("STORE_CLOSED")


def _prepare(item: StoreItem, limits: StoreLimits) -> dict[str, str]:
    if item.truth_kind in FORBIDDEN_TRUTH or item.verification_state in FORBIDDEN_TRUTH:
        raise StoreError("UNPROVEN_AUTHORITY")
    if item.truth_kind not in ALLOWED_TRUTH:
        raise StoreError("RECORD_INVALID")
    if not item.source_type or not item.source_identifier or not item.record_type:
        raise StoreError("RECORD_INVALID")
    if not item.collected_at or not isinstance(item.collected_at, str):
        raise StoreError("RECORD_INVALID")
    leaf = (item.relative_path or item.source_identifier).rsplit("/", 1)[-1]
    if secret_filename(leaf):
        raise StoreError("SECRET_EXCLUDED")
    title = item.title.strip()
    content = item.content
    blob = (title + "\n" + content).encode("utf-8")
    if len(blob) > limits.max_record_bytes:
        raise StoreError("OVERSIZED")
    if secret_bytes(blob) or secret_bytes(title.encode("utf-8")):
        raise StoreError("SECRET_EXCLUDED")
    digest = item.content_hash or hashlib.sha256(content.encode("utf-8")).hexdigest()
    metadata = {str(key): str(value) for key, value in dict(item.metadata or {}).items()}
    return {
        "logical_key": logical_key(item),
        "record_id": version_id(item, digest),
        "title": title,
        "content": content,
        "content_hash": digest,
        "verification_state": item.verification_state or "UNVERIFIED",
        "truth_kind": item.truth_kind,
        "metadata_json": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    }


def _presence_for(record_type: str) -> tuple[str, str]:
    if record_type == "GIT_COMMIT":
        return "HISTORICAL", "HISTORICAL"
    return "CURRENT", "CURRENT"


def _public_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "schema_version": row["schema_version"],
        "source_type": row["source_type"],
        "source_identifier": row["source_identifier"],
        "record_type": row["record_type"],
        "title": row["title"],
        "content": row["content"],
        "content_hash": row["content_hash"],
        "collected_at": row["collected_at"],
        "indexed_at": row["indexed_at"],
        "last_seen_at": row["last_seen_at"],
        "verification_state": row["verification_state"],
        "authority_scope": row["authority_scope"],
        "truth_kind": row["truth_kind"],
        "freshness": row["freshness"],
        "presence": row["presence"],
        "relative_path": row["relative_path"],
        "commit_sha": row["commit_sha"],
        "branch": row["branch"],
        "worktree": row["worktree"],
        "reported_at": row["reported_at"],
        "observed_at": row["observed_at"],
        "source_timestamp": row["source_timestamp"],
        "source_account": row["source_account"],
        "conversation_id": row["conversation_id"],
        "message_id": row["message_id"],
        "workstream": row["workstream"],
        "superseded_by": row["superseded_by"],
        "metadata": json.loads(row["metadata_json"]),
    }
