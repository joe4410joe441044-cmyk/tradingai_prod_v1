"""Bounded, append-safe audit authority for the Supervisor trigger POST route.

This is the Supervisor trigger audit authority: a dedicated, explicit-path SQLite
table that stores only bounded, sanitized trigger attempts.  It is an additive
extension of the existing Supervisor audit infrastructure (the shared
``SupervisorHistoryEvent`` contract cannot express a trigger attempt without
inventing provider/agent identity, so a dedicated table is used rather than
misrepresenting a trigger as a shadow assessment).

Safety properties:

- importing the module performs no I/O;
- constructing the store performs no I/O and requires an explicit absolute path
  (there is no automatically active Production default);
- the database is opened only by an explicit ``initialize``/``append``/``list``;
- append is a single transaction with a unique ``audit_id``;
- only bounded, sanitized fields are stored; no credentials, cookies, auth
  headers, raw CSRF tokens, raw request body, prompts, exchange credentials or
  trading secrets are stored;
- reads are bounded by ``limit`` with an opaque cursor and a hard page cap.
"""
from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from .monitoring_models import Contract, Count, Token, aware

AUDIT_SCHEMA_VERSION = "supervisor-trigger-audit-v1"
AUDIT_EVENT_TYPE = "SUPERVISOR_MONITORING_TRIGGER"
AUDIT_MAX_ENTRIES = 5000
AUDIT_MAX_LIMIT = 100

_SCHEMA_VERSION_KEY = "schema_version"

_CREATE_META = "CREATE TABLE IF NOT EXISTS trigger_audit_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
_CREATE_EVENTS = (
    "CREATE TABLE IF NOT EXISTS trigger_audit_events ("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
    "audit_id TEXT NOT NULL UNIQUE, "
    "occurred_at TEXT NOT NULL, "
    "outcome TEXT NOT NULL, "
    "http_status INTEGER NOT NULL, "
    "payload TEXT NOT NULL)"
)


class TriggerAuditError(Exception):
    """A bounded, presentation-safe audit failure with a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class SupervisorTriggerAuditRecord(Contract):
    """Bounded, sanitized trigger audit record.  Never carries raw secrets."""

    schema_version: Token = AUDIT_SCHEMA_VERSION
    audit_id: Token
    event_type: Token = AUDIT_EVENT_TYPE
    principal_ref: Token | None = None
    capability_decision: Token = "NOT_EVALUATED"
    request_fingerprint: Token | None = None
    idempotency_key_digest: Token | None = None
    outcome: Token
    http_status: Count
    occurred_at: datetime
    duration_ms: Count = 0
    replay: bool = False
    conflict: bool = False
    busy: bool = False
    correlation_id: Token | None = None
    failure_code: Token | None = None
    redacted: bool = False
    warnings: tuple[Token, ...] = Field(default=(), max_length=32)

    _aware = field_validator("occurred_at")(aware)

    @field_validator("warnings")
    @classmethod
    def _ordered(cls, value):
        return tuple(sorted(set(value)))


class SupervisorTriggerAuditPage(Contract):
    records: tuple[SupervisorTriggerAuditRecord, ...]
    next_cursor: Token | None = None
    order: Literal["NEWEST_FIRST"] = "NEWEST_FIRST"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupervisorTriggerAuditStore:
    """Explicit-path bounded trigger audit store.  Constructor is side-effect free."""

    def __init__(
        self,
        path: str | Path | None,
        *,
        max_entries: int = AUDIT_MAX_ENTRIES,
        clock=None,
    ) -> None:
        if path is None or isinstance(path, bool):
            raise TypeError("an explicit audit database path is required")
        candidate = Path(path)
        if str(candidate).strip() in ("", "."):
            raise TypeError("an explicit audit database path is required")
        if not candidate.is_absolute():
            raise ValueError("the audit database path must be absolute")
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.path = candidate
        self.max_entries = max_entries
        self._clock = clock if clock is not None else _utcnow
        self._initialized = False

    # -- configuration ------------------------------------------------------

    def _validate_path(self, *, create_parent: bool) -> None:
        if self.path.is_symlink():
            raise TriggerAuditError("PATH_SYMLINK_REJECTED")
        if self.path.exists():
            if not self.path.is_file():
                raise TriggerAuditError("PATH_NOT_REGULAR")
            return
        parent = self.path.parent
        if parent.exists():
            if not parent.is_dir():
                raise TriggerAuditError("PATH_NOT_DIRECTORY")
            return
        if create_parent:
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise TriggerAuditError("PATH_PARENT_MISSING") from exc
            return
        raise TriggerAuditError("PATH_PARENT_MISSING")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=2.0, isolation_level=None)

    def initialize(self, *, create_parent: bool = False) -> None:
        """Explicitly create/validate the audit database and versioned schema."""

        self._validate_path(create_parent=create_parent)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self._validate_path(create_parent=False)
        conn = self._connect()
        try:
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_META)
            conn.execute(_CREATE_EVENTS)
            row = conn.execute(
                "SELECT v FROM trigger_audit_meta WHERE k=?", (_SCHEMA_VERSION_KEY,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO trigger_audit_meta(k, v) VALUES(?, ?)",
                    (_SCHEMA_VERSION_KEY, AUDIT_SCHEMA_VERSION),
                )
            elif row[0] != AUDIT_SCHEMA_VERSION:
                conn.execute("ROLLBACK")
                raise TriggerAuditError("SCHEMA_UNSUPPORTED")
            conn.execute("COMMIT")
        except TriggerAuditError:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise TriggerAuditError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self._initialized = True

    # -- writes --------------------------------------------------------------

    def append(self, record: SupervisorTriggerAuditRecord) -> None:
        """Append one sanitized record.  Raises TriggerAuditError on failure."""

        if not isinstance(record, SupervisorTriggerAuditRecord):
            raise TriggerAuditError("RECORD_INVALID")
        try:
            payload = record.stable_json()
        except Exception as exc:  # noqa: BLE001
            raise TriggerAuditError("RECORD_INVALID") from exc
        if len(payload.encode("utf-8")) > 16 * 1024:
            raise TriggerAuditError("RECORD_TOO_LARGE")
        self._ensure_schema()
        conn = self._connect()
        try:
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            total = conn.execute("SELECT COUNT(*) FROM trigger_audit_events").fetchone()[0]
            if total >= self.max_entries:
                conn.execute("ROLLBACK")
                raise TriggerAuditError("STORE_FULL")
            conn.execute(
                "INSERT INTO trigger_audit_events(audit_id, occurred_at, outcome, http_status, payload) "
                "VALUES(?,?,?,?,?)",
                (record.audit_id, record.occurred_at.isoformat(), record.outcome,
                 record.http_status, payload),
            )
            conn.execute("COMMIT")
        except TriggerAuditError:
            raise
        except sqlite3.IntegrityError as exc:
            raise TriggerAuditError("DUPLICATE_EVENT") from exc
        except sqlite3.Error as exc:
            raise TriggerAuditError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()

    def count(self) -> int:
        self._ensure_schema()
        conn = self._connect()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM trigger_audit_events").fetchone()[0])
        except sqlite3.Error as exc:
            raise TriggerAuditError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()

    # -- reads ---------------------------------------------------------------

    @staticmethod
    def _cursor(seq: int) -> str:
        return base64.urlsafe_b64encode(str(seq).encode()).decode().rstrip("=")

    @staticmethod
    def _decode(value: str) -> int:
        try:
            return int(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode())
        except Exception as exc:  # noqa: BLE001
            raise TriggerAuditError("CURSOR_INVALID") from exc

    def list(self, *, limit: int = 20, cursor: str | None = None) -> SupervisorTriggerAuditPage:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= AUDIT_MAX_LIMIT:
            raise TriggerAuditError("INPUT_INVALID")
        clause = ""
        args: list[Any] = []
        if cursor:
            clause = " WHERE seq<?"
            args.append(self._decode(cursor))
        self._ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT seq, payload FROM trigger_audit_events{clause} ORDER BY seq DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
        except sqlite3.Error as exc:
            raise TriggerAuditError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()
        records = []
        corrupt = 0
        for row in rows[:limit]:
            try:
                records.append(SupervisorTriggerAuditRecord.model_validate_json(row[1]))
            except Exception:  # noqa: BLE001 - corrupt rows are isolated
                corrupt += 1
        next_cursor = self._cursor(rows[limit - 1][0]) if len(rows) > limit else None
        if corrupt:
            records = [r.model_copy(update={"warnings": tuple(sorted(set(r.warnings) | {"AUDIT_ROW_CORRUPT"}))}) for r in records]
        return SupervisorTriggerAuditPage(records=tuple(records), next_cursor=next_cursor)


__all__ = [
    "AUDIT_EVENT_TYPE",
    "AUDIT_MAX_ENTRIES",
    "AUDIT_MAX_LIMIT",
    "AUDIT_SCHEMA_VERSION",
    "SupervisorTriggerAuditPage",
    "SupervisorTriggerAuditRecord",
    "SupervisorTriggerAuditStore",
    "TriggerAuditError",
]
