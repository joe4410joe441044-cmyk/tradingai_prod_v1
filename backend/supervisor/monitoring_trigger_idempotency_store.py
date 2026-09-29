"""Restart-safe SQLite API-idempotency authority for the future Supervisor
manual-trigger route.

This module implements **only** the durable idempotency store designed in
Phase 3D-2.  It does not implement the OS advisory ownership lock, does not add
an API route, does not import or invoke the manual monitoring runner, does not
execute monitoring and does not connect Production.

Safety properties:

- importing the module performs no I/O;
- constructing the store performs no I/O and requires an explicit database path
  (there is no automatically active Production default);
- the database is opened only by an explicit ``initialize`` call or by an
  operation method;
- the claim path uses one ``BEGIN IMMEDIATE`` transaction so that a
  read-then-write race cannot acquire the same claim twice;
- every mutation is generation/owner checked and fails closed;
- bounded response summaries are the only payload persisted, and no credential,
  cookie, authorisation header, CSRF token, raw trace or stack trace is stored.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping

from pydantic import Field, field_validator

from .monitoring_models import Contract, Count, Token, aware

SCHEMA_VERSION = "supervisor-trigger-idempotency-v1"

IdempotencyStatus = Literal[
    "CLAIMED",
    "IN_PROGRESS",
    "COMPLETED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "EXPIRED",
    "CONFLICT",
    "CORRUPT",
]
ClaimDecision = Literal[
    "CLAIM_ACQUIRED",
    "REPLAY_COMPLETED",
    "ALREADY_IN_PROGRESS",
    "CONFLICT",
    "RETRY_ALLOWED",
    "EXPIRED_RECLAIMED",
    "AUTHORITY_UNAVAILABLE",
    "CORRUPT",
]
TransitionDecision = Literal[
    "APPLIED",
    "ALREADY_COMPLETED",
    "STALE_GENERATION",
    "WRONG_OWNER",
    "ILLEGAL_TRANSITION",
    "NOT_FOUND",
    "CONFLICT",
    "REJECTED",
    "AUTHORITY_UNAVAILABLE",
    "CORRUPT",
]
RecoveryDecision = Literal[
    "RECLAIMED",
    "BLOCKED",
    "NOT_RECLAIMABLE",
    "TERMINAL",
    "GENERATION_MISMATCH",
    "NOT_FOUND",
    "AUTHORITY_UNAVAILABLE",
    "CORRUPT",
]

ACTIVE_STATUSES = frozenset({"CLAIMED", "IN_PROGRESS"})
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED_RETRYABLE", "FAILED_FINAL"})
CLEANABLE_STATUSES = frozenset(
    {"COMPLETED", "FAILED_RETRYABLE", "FAILED_FINAL", "EXPIRED", "CONFLICT", "CORRUPT"}
)
VALID_STATUSES = frozenset(IdempotencyStatus.__args__)

DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_LEASE_SECONDS = 5 * 60
MAX_TTL_SECONDS = 7 * 24 * 60 * 60

_MAX_RESPONSE_BYTES = 16 * 1024
_MAX_RESPONSE_DEPTH = 4
_MAX_RESPONSE_ITEMS = 64
_MAX_RESPONSE_WARNINGS = 64

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SECRET_MARKERS = ("API_KEY", "APIKEY", "PASSWORD", "PRIVATE_KEY", "SECRET", "BEARER", "TOKEN")
_FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "password",
        "api_key",
        "apikey",
        "authorization",
        "authorization_header",
        "cookie",
        "cookies",
        "session",
        "session_token",
        "session_id",
        "csrf",
        "csrf_token",
        "token",
        "secret",
        "private_key",
        "raw_body",
        "raw_request",
        "raw_evidence",
        "evidence",
        "trace",
        "traceback",
        "stack_trace",
        "exception",
    }
)

SCHEMA_VERSION_KEY = "schema_version"

_CREATE_META = (
    "CREATE TABLE IF NOT EXISTS idempotency_meta ("
    "k TEXT PRIMARY KEY, v TEXT NOT NULL)"
)
_CREATE_RECORDS = (
    "CREATE TABLE IF NOT EXISTS idempotency_records ("
    "operation TEXT NOT NULL, "
    "principal_scope TEXT NOT NULL, "
    "idempotency_key TEXT NOT NULL, "
    "request_fingerprint TEXT NOT NULL, "
    "status TEXT NOT NULL CHECK(status IN ("
    "'CLAIMED','IN_PROGRESS','COMPLETED','FAILED_RETRYABLE','FAILED_FINAL',"
    "'EXPIRED','CONFLICT','CORRUPT')), "
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "expires_at TEXT NOT NULL, "
    "run_id TEXT, "
    "owner_id TEXT, "
    "generation INTEGER NOT NULL CHECK(generation >= 1), "
    "attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0), "
    "lease_expires_at TEXT, "
    "response_json TEXT, "
    "response_digest TEXT, "
    "error_class TEXT, "
    "schema_version TEXT NOT NULL, "
    "CHECK(length(idempotency_key) BETWEEN 1 AND 512), "
    "CHECK(length(operation) BETWEEN 1 AND 512), "
    "CHECK(length(principal_scope) BETWEEN 1 AND 512), "
    "CHECK(length(request_fingerprint) BETWEEN 1 AND 512), "
    "PRIMARY KEY (operation, principal_scope, idempotency_key))"
)
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_idem_status ON idempotency_records(status)",
    "CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency_records(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_idem_updated ON idempotency_records(updated_at)",
)

_RECORD_COLUMNS = (
    "operation, principal_scope, idempotency_key, request_fingerprint, status, "
    "created_at, updated_at, expires_at, run_id, owner_id, generation, "
    "attempt_count, lease_expires_at, response_json, response_digest, error_class"
)

_INSERT_CLAIM_SQL = (
    "INSERT INTO idempotency_records("
    "operation, principal_scope, idempotency_key, request_fingerprint, status, "
    "created_at, updated_at, expires_at, run_id, owner_id, generation, "
    "attempt_count, lease_expires_at, response_json, response_digest, error_class, "
    "schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


class IdempotencyStoreError(Exception):
    """A bounded, presentation-safe store failure with a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class IdempotencyLimits:
    """Bounded configuration; safe defaults suitable for tests and services."""

    max_key_length: int = 128
    max_operation_length: int = 64
    max_principal_scope_length: int = 128
    max_fingerprint_length: int = 128
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    max_query_limit: int = 100
    max_recovery_scan: int = 500
    max_cleanup_batch: int = 500
    max_active_claims: int = 1000
    max_records: int = 100000
    completed_retention_seconds: int = 24 * 60 * 60
    failed_retention_seconds: int = 7 * 24 * 60 * 60
    default_ttl_seconds: int = DEFAULT_TTL_SECONDS
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    timeout_seconds: float = 2.0


class ClaimResult(Contract):
    decision: ClaimDecision
    reason_code: Token
    key: Token | None = None
    operation: Token | None = None
    principal_scope: Token | None = None
    status: IdempotencyStatus | None = None
    generation: Count | None = None
    run_id: Token | None = None
    owner_id: Token | None = None
    replay: bool = False
    retryable: bool = False
    response: dict[str, Any] | None = None


class TransitionResult(Contract):
    applied: bool = False
    decision: TransitionDecision
    reason_code: Token
    key: Token | None = None
    operation: Token | None = None
    principal_scope: Token | None = None
    status: IdempotencyStatus | None = None
    generation: Count | None = None
    run_id: Token | None = None
    idempotent: bool = False
    response: dict[str, Any] | None = None


class ReadResult(Contract):
    found: bool
    reason_code: Token = "NOT_FOUND"
    status: IdempotencyStatus | None = None
    generation: Count | None = None
    run_id: Token | None = None
    expired: bool = False
    response: dict[str, Any] | None = None


class RecoveryResult(Contract):
    decision: RecoveryDecision
    reason_code: Token
    reclaimed: bool = False
    key: Token | None = None
    operation: Token | None = None
    principal_scope: Token | None = None
    status: IdempotencyStatus | None = None
    generation: Count | None = None


class RecordView(Contract):
    operation: Token
    principal_scope: Token
    key: Token
    request_fingerprint: Token
    status: IdempotencyStatus
    generation: Count
    attempt_count: Count
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    run_id: Token | None = None
    owner_id: Token | None = None
    lease_expires_at: datetime | None = None
    error_class: Token | None = None
    response: dict[str, Any] | None = None

    _aware = field_validator("created_at", "updated_at", "expires_at")(
        lambda value: aware(value)
    )
    _aware_optional = field_validator("lease_expires_at")(
        lambda value: None if value is None else aware(value)
    )


class RecoveryCandidate(Contract):
    operation: Token
    principal_scope: Token
    key: Token
    status: IdempotencyStatus
    generation: Count
    updated_at: datetime
    expires_at: datetime
    owner_id: Token | None = None
    run_id: Token | None = None

    _aware = field_validator("updated_at", "expires_at")(lambda value: aware(value))


class CleanupResult(Contract):
    scanned: Count
    deleted: Count
    reason_code: Token = "CLEANUP_COMPLETE"


class CorruptionReport(Contract):
    integrity_ok: bool
    checked: bool = True
    errors: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("errors")
    @classmethod
    def _bounded_errors(cls, values):
        return tuple(str(value)[:128] for value in values)


def new_owner_id() -> str:
    """A fresh, bounded, secret-free owner reference."""

    return "O" + secrets.token_hex(16)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return aware(value).isoformat()


def _parse_iso(value: str) -> datetime:
    try:
        return aware(datetime.fromisoformat(value))
    except Exception as exc:  # noqa: BLE001 - mapped to bounded corruption
        raise IdempotencyStoreError("RECORD_CORRUPT", "unparseable timestamp") from exc


def _check_token(value: Any, name: str, max_length: int) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise IdempotencyStoreError("INPUT_INVALID", f"{name} must be text")
    if not 1 <= len(value) <= max_length:
        raise IdempotencyStoreError("INPUT_INVALID", f"{name} length out of range")
    if not _TOKEN_RE.match(value):
        raise IdempotencyStoreError("INPUT_INVALID", f"{name} has invalid characters")
    upper = value.upper()
    if any(marker in upper for marker in _SECRET_MARKERS):
        raise IdempotencyStoreError("INPUT_INVALID", f"{name} looks secret-like")
    return value


def _sanitize_scalar(value: Any, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise IdempotencyStoreError("RESPONSE_INVALID", "non-finite float")
        return value
    if isinstance(value, str):
        if len(value) > 4096:
            raise IdempotencyStoreError("RESPONSE_INVALID", "string element too long")
        if any(ord(ch) < 32 for ch in value):
            raise IdempotencyStoreError("RESPONSE_INVALID", "control character")
        if "/" in value or "\\" in value or "://" in value:
            raise IdempotencyStoreError("RESPONSE_FORBIDDEN", "path or URL in response")
        upper = value.upper()
        if any(marker in upper for marker in _SECRET_MARKERS):
            raise IdempotencyStoreError("RESPONSE_FORBIDDEN", "secret-like response value")
        if value.startswith(("sk-", "eyJ")):
            raise IdempotencyStoreError("RESPONSE_FORBIDDEN", "secret-like response value")
        return value
    raise IdempotencyStoreError("RESPONSE_INVALID", "unsupported response value type")


def _sanitize_response_mapping(value: Mapping, depth: int) -> dict:
    if depth > _MAX_RESPONSE_DEPTH:
        raise IdempotencyStoreError("RESPONSE_INVALID", "response nesting too deep")
    if len(value) > _MAX_RESPONSE_ITEMS:
        raise IdempotencyStoreError("RESPONSE_INVALID", "too many response keys")
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise IdempotencyStoreError("RESPONSE_INVALID", "response keys must be text")
        lowered = key.lower()
        if lowered in _FORBIDDEN_RESPONSE_KEYS:
            raise IdempotencyStoreError("RESPONSE_FORBIDDEN", "forbidden response key")
        if isinstance(item, Mapping):
            if lowered in ("warnings", "errors") and len(item) > _MAX_RESPONSE_WARNINGS:
                raise IdempotencyStoreError("RESPONSE_INVALID", "too many warnings")
            cleaned[key] = _sanitize_response_mapping(item, depth + 1)
        elif isinstance(item, (list, tuple)):
            if len(item) > _MAX_RESPONSE_ITEMS:
                raise IdempotencyStoreError("RESPONSE_INVALID", "too many response items")
            cleaned[key] = [_sanitize_any(entry, depth + 1) for entry in item]
        else:
            cleaned[key] = _sanitize_scalar(item, depth)
    return cleaned


def _sanitize_any(value: Any, depth: int) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_response_mapping(value, depth)
    if isinstance(value, (list, tuple)):
        if depth > _MAX_RESPONSE_DEPTH:
            raise IdempotencyStoreError("RESPONSE_INVALID", "response nesting too deep")
        if len(value) > _MAX_RESPONSE_ITEMS:
            raise IdempotencyStoreError("RESPONSE_INVALID", "too many response items")
        return [_sanitize_any(entry, depth + 1) for entry in value]
    return _sanitize_scalar(value, depth)


def _serialize_response(
    response: Mapping | Contract | None, max_bytes: int
) -> tuple[str | None, str | None]:
    """Return (canonical_json, digest) or (None, None). Raises bounded errors."""

    if response is None:
        return None, None
    if isinstance(response, Contract):
        payload = response.model_dump(mode="json")
    elif isinstance(response, Mapping):
        payload = dict(response)
    else:
        raise IdempotencyStoreError("RESPONSE_INVALID", "response must be a mapping")
    cleaned = _sanitize_any(payload, 0)
    try:
        text = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise IdempotencyStoreError("RESPONSE_NOT_JSON", "response is not JSON-compatible") from exc
    if len(text.encode("utf-8")) > max_bytes:
        raise IdempotencyStoreError("RESPONSE_TOO_LARGE", "response exceeds the size bound")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def _parse_response(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise IdempotencyStoreError("RECORD_CORRUPT", "stored response is not an object")
    return loaded


class MonitoringTriggerIdempotencyStore:
    """Durable, restart-safe API-idempotency authority backed by SQLite.

    The constructor is side-effect free and never creates or opens the database.
    Only :meth:`initialize` and the operation methods touch the filesystem.
    """

    def __init__(
        self,
        path: str | os.PathLike | None,
        *,
        schema_version: str = SCHEMA_VERSION,
        limits: IdempotencyLimits | None = None,
        **overrides: Any,
    ) -> None:
        if path is None or isinstance(path, bool):
            raise TypeError("an explicit idempotency database path is required")
        candidate = Path(path)
        if str(candidate).strip() in ("", "."):
            raise TypeError("an explicit idempotency database path is required")
        self.path = candidate
        self.schema_version = _check_token(schema_version, "schema_version", 128)
        base = limits or IdempotencyLimits()
        if overrides:
            base = replace(base, **overrides)
        self._validate_limits(base)
        self.limits = base
        self._initialized = False

    # -- configuration ------------------------------------------------------

    @staticmethod
    def _validate_limits(limits: IdempotencyLimits) -> None:
        for name in ("max_key_length", "max_operation_length", "max_principal_scope_length",
                     "max_fingerprint_length", "max_query_limit", "max_recovery_scan",
                     "max_cleanup_batch", "max_active_claims", "max_records",
                     "completed_retention_seconds", "failed_retention_seconds",
                     "default_ttl_seconds", "lease_seconds"):
            value = getattr(limits, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 1 <= limits.max_response_bytes <= 1024 * 1024:
            raise ValueError("max_response_bytes out of range")
        if limits.timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")

    # -- low-level helpers ---------------------------------------------------

    def _validate_path(self, *, create_parent: bool) -> None:
        if self.path.is_symlink():
            raise IdempotencyStoreError("PATH_SYMLINK_REJECTED", "database path is a symlink")
        if self.path.exists():
            if not self.path.is_file():
                raise IdempotencyStoreError("PATH_NOT_REGULAR", "database path is not a file")
            return
        parent = self.path.parent
        if parent.exists():
            if not parent.is_dir():
                raise IdempotencyStoreError("PATH_NOT_DIRECTORY", "database parent is not a directory")
            return
        if create_parent:
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise IdempotencyStoreError("PATH_PARENT_MISSING", "cannot create database parent") from exc
            return
        raise IdempotencyStoreError("PATH_PARENT_MISSING", "database parent does not exist")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            str(self.path), timeout=self.limits.timeout_seconds, isolation_level=None
        )

    def _configure(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute(f"PRAGMA busy_timeout={int(self.limits.timeout_seconds * 1000)}")
        except sqlite3.Error:
            pass
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass
        try:
            conn.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error:
            pass

    def _harden_file(self) -> None:
        try:
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            self._configure(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        finally:
            conn.close()

    def _schema_state(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency_meta'"
        ).fetchone()
        if row is None:
            return "ABSENT"
        version = conn.execute(
            "SELECT v FROM idempotency_meta WHERE k=?", (SCHEMA_VERSION_KEY,)
        ).fetchone()
        if version is None:
            return "CORRUPT"
        return "MATCH" if version[0] == self.schema_version else "UNSUPPORTED"

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self._validate_path(create_parent=False)
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            self._configure(conn)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
            conn.execute("BEGIN IMMEDIATE")
            state = self._schema_state(conn)
            if state == "UNSUPPORTED":
                conn.execute("ROLLBACK")
                raise IdempotencyStoreError("SCHEMA_UNSUPPORTED", "unsupported schema version")
            if state == "CORRUPT":
                conn.execute("ROLLBACK")
                raise IdempotencyStoreError("DATABASE_CORRUPT", "schema metadata is corrupt")
            if state == "ABSENT":
                conn.execute(_CREATE_META)
                conn.execute(_CREATE_RECORDS)
                for statement in _CREATE_INDEXES:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO idempotency_meta(k, v) VALUES(?, ?)",
                    (SCHEMA_VERSION_KEY, self.schema_version),
                )
            else:
                conn.execute(_CREATE_RECORDS)
                for statement in _CREATE_INDEXES:
                    conn.execute(statement)
            conn.execute("COMMIT")
        except IdempotencyStoreError:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise IdempotencyStoreError("DATABASE_CORRUPT", "database is corrupt") from exc
        except sqlite3.Error as exc:
            if conn is not None:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise IdempotencyStoreError("DATABASE_UNAVAILABLE", "database unavailable") from exc
        finally:
            if conn is not None:
                conn.close()
        self._harden_file()
        self._initialized = True

    def initialize(self, *, create_parent: bool = False) -> None:
        """Explicitly create/validate the database and versioned schema."""

        self._validate_path(create_parent=create_parent)
        self._ensure_schema()

    # -- input helpers -------------------------------------------------------

    def _now(self, now: datetime | None) -> datetime:
        if now is None:
            return _utcnow()
        return aware(now)

    def _owner(self, owner_id: str | None) -> str:
        if owner_id is None:
            return new_owner_id()
        return _check_token(owner_id, "owner_id", self.limits.max_principal_scope_length)

    def _resolve_expiry(
        self, now: datetime, expires_at: datetime | None, ttl_seconds: int | None
    ) -> datetime:
        if expires_at is not None:
            candidate = aware(expires_at)
            if candidate <= now:
                raise IdempotencyStoreError("INPUT_INVALID", "expires_at must be in the future")
            if candidate > now + timedelta(seconds=MAX_TTL_SECONDS):
                raise IdempotencyStoreError("INPUT_INVALID", "expires_at too far in the future")
            return candidate
        ttl = self.limits.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if not isinstance(ttl, int) or isinstance(ttl, bool) or not 1 <= ttl <= MAX_TTL_SECONDS:
            raise IdempotencyStoreError("INPUT_INVALID", "ttl_seconds out of range")
        return now + timedelta(seconds=ttl)

    def _check_fingerprint(self, value: Any) -> str:
        return _check_token(value, "request_fingerprint", self.limits.max_fingerprint_length)

    def _is_expired(self, now: datetime, status: str, expires_at: str) -> bool:
        if status == "EXPIRED":
            return True
        return now >= _parse_iso(expires_at)

    def _row_to_view(self, row: sqlite3.Row | tuple) -> RecordView:
        try:
            return RecordView(
                operation=row[0],
                principal_scope=row[1],
                key=row[2],
                request_fingerprint=row[3],
                status=row[4],
                created_at=_parse_iso(row[5]),
                updated_at=_parse_iso(row[6]),
                expires_at=_parse_iso(row[7]),
                run_id=row[8],
                owner_id=row[9],
                generation=row[10],
                attempt_count=row[11],
                lease_expires_at=None if row[12] is None else _parse_iso(row[12]),
                response=_parse_response(row[13]),
                error_class=row[15],
            )
        except IdempotencyStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - malformed row is corruption
            raise IdempotencyStoreError("RECORD_CORRUPT", "malformed record row") from exc

    @staticmethod
    def _valid_row_status(row: tuple) -> bool:
        return row[4] in VALID_STATUSES

    @staticmethod
    def _insert_claim(conn: sqlite3.Connection, params: tuple) -> None:
        conn.execute(_INSERT_CLAIM_SQL, params)

    # -- atomic claim --------------------------------------------------------

    def claim(
        self,
        *,
        key: str,
        request_fingerprint: str,
        principal_scope: str,
        operation: str,
        now: datetime | None = None,
        owner_id: str | None = None,
        expires_at: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> ClaimResult:
        """One atomic transaction decides and records the claim outcome."""

        clean_key = _check_token(key, "key", self.limits.max_key_length)
        clean_scope = _check_token(
            principal_scope, "principal_scope", self.limits.max_principal_scope_length
        )
        clean_op = _check_token(operation, "operation", self.limits.max_operation_length)
        clean_fp = self._check_fingerprint(request_fingerprint)
        moment = self._now(now)
        owner = self._owner(owner_id)
        expiry = self._resolve_expiry(moment, expires_at, ttl_seconds)

        try:
            self._ensure_schema()
        except IdempotencyStoreError as exc:
            return self._claim_failure(exc, clean_key, clean_op, clean_scope)

        try:
            with self._transaction() as conn:
                row = conn.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM idempotency_records "
                    "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                    (clean_op, clean_scope, clean_key),
                ).fetchone()
                if row is None:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM idempotency_records"
                    ).fetchone()[0]
                    active = conn.execute(
                        "SELECT COUNT(*) FROM idempotency_records "
                        "WHERE status IN ('CLAIMED','IN_PROGRESS')"
                    ).fetchone()[0]
                    if total >= self.limits.max_records or active >= self.limits.max_active_claims:
                        return ClaimResult(
                            decision="AUTHORITY_UNAVAILABLE",
                            reason_code="CAPACITY_EXHAUSTED",
                            key=clean_key,
                            operation=clean_op,
                            principal_scope=clean_scope,
                        )
                    self._insert_claim(
                        conn,
                        (
                            clean_op, clean_scope, clean_key, clean_fp, "CLAIMED",
                            _iso(moment), _iso(moment), _iso(expiry), None, owner, 1, 0,
                            _iso(moment + timedelta(seconds=self.limits.lease_seconds)),
                            None, None, None, self.schema_version,
                        ),
                    )
                    return ClaimResult(
                        decision="CLAIM_ACQUIRED",
                        reason_code="NEW_CLAIM",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status="CLAIMED",
                        generation=1,
                        owner_id=owner,
                    )
                if not self._valid_row_status(row):
                    return ClaimResult(
                        decision="CORRUPT",
                        reason_code="RECORD_CORRUPT",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                    )
                stored_status = row[4]
                stored_generation = row[10]
                if row[3] != clean_fp:
                    return ClaimResult(
                        decision="CONFLICT",
                        reason_code="FINGERPRINT_MISMATCH",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status=stored_status,
                        generation=stored_generation,
                    )
                if self._is_expired(moment, stored_status, row[7]):
                    generation = stored_generation + 1
                    conn.execute(
                        "UPDATE idempotency_records SET status='CLAIMED', owner_id=?, "
                        "generation=?, attempt_count=attempt_count+1, run_id=NULL, "
                        "response_json=NULL, response_digest=NULL, error_class=NULL, "
                        "updated_at=?, expires_at=?, lease_expires_at=? "
                        "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                        (
                            owner, generation, _iso(moment), _iso(expiry),
                            _iso(moment + timedelta(seconds=self.limits.lease_seconds)),
                            clean_op, clean_scope, clean_key,
                        ),
                    )
                    return ClaimResult(
                        decision="EXPIRED_RECLAIMED",
                        reason_code="EXPIRED_RECLAIMED",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status="CLAIMED",
                        generation=generation,
                        owner_id=owner,
                    )
                if stored_status == "COMPLETED":
                    return ClaimResult(
                        decision="REPLAY_COMPLETED",
                        reason_code="REPLAY",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status=stored_status,
                        generation=stored_generation,
                        run_id=row[8],
                        replay=True,
                        response=_parse_response(row[13]),
                    )
                if stored_status in ACTIVE_STATUSES:
                    return ClaimResult(
                        decision="ALREADY_IN_PROGRESS",
                        reason_code="IN_PROGRESS",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status=stored_status,
                        generation=stored_generation,
                        run_id=row[8],
                    )
                if stored_status == "FAILED_RETRYABLE":
                    generation = stored_generation + 1
                    conn.execute(
                        "UPDATE idempotency_records SET status='CLAIMED', owner_id=?, "
                        "generation=?, attempt_count=attempt_count+1, run_id=NULL, "
                        "response_json=NULL, response_digest=NULL, error_class=NULL, "
                        "updated_at=?, expires_at=?, lease_expires_at=? "
                        "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                        (
                            owner, generation, _iso(moment), _iso(expiry),
                            _iso(moment + timedelta(seconds=self.limits.lease_seconds)),
                            clean_op, clean_scope, clean_key,
                        ),
                    )
                    return ClaimResult(
                        decision="RETRY_ALLOWED",
                        reason_code="RETRY_ALLOWED",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status="CLAIMED",
                        generation=generation,
                        owner_id=owner,
                        retryable=True,
                    )
                if stored_status == "FAILED_FINAL":
                    return ClaimResult(
                        decision="CONFLICT",
                        reason_code="TERMINAL_FAILURE",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                        status=stored_status,
                        generation=stored_generation,
                    )
                if stored_status == "CORRUPT":
                    return ClaimResult(
                        decision="CORRUPT",
                        reason_code="RECORD_CORRUPT",
                        key=clean_key,
                        operation=clean_op,
                        principal_scope=clean_scope,
                    )
                return ClaimResult(
                    decision="CONFLICT",
                    reason_code="RECORD_CONFLICT",
                    key=clean_key,
                    operation=clean_op,
                    principal_scope=clean_scope,
                    status=stored_status,
                    generation=stored_generation,
                )
        except sqlite3.OperationalError as exc:
            return self._claim_failure(
                IdempotencyStoreError("DATABASE_BUSY", str(exc)),
                clean_key, clean_op, clean_scope,
            )
        except sqlite3.DatabaseError as exc:
            return self._claim_failure(
                IdempotencyStoreError("DATABASE_CORRUPT", str(exc)),
                clean_key, clean_op, clean_scope,
            )
        except sqlite3.Error as exc:
            return self._claim_failure(
                IdempotencyStoreError("DATABASE_UNAVAILABLE", str(exc)),
                clean_key, clean_op, clean_scope,
            )

    @staticmethod
    def _claim_failure(
        exc: IdempotencyStoreError, key: str, operation: str, principal_scope: str
    ) -> ClaimResult:
        if exc.code in ("DATABASE_CORRUPT", "RECORD_CORRUPT"):
            decision: ClaimDecision = "CORRUPT"
        else:
            decision = "AUTHORITY_UNAVAILABLE"
        return ClaimResult(
            decision=decision,
            reason_code=exc.code[:128] or "AUTHORITY_UNAVAILABLE",
            key=key,
            operation=operation,
            principal_scope=principal_scope,
        )

    # -- transitions ---------------------------------------------------------

    def _transition_failure(
        self, exc: IdempotencyStoreError, key: str, operation: str, principal_scope: str
    ) -> TransitionResult:
        if exc.code in ("DATABASE_CORRUPT", "RECORD_CORRUPT"):
            decision: TransitionDecision = "CORRUPT"
        else:
            decision = "AUTHORITY_UNAVAILABLE"
        return TransitionResult(
            decision=decision,
            reason_code=exc.code[:128] or "AUTHORITY_UNAVAILABLE",
            key=key,
            operation=operation,
            principal_scope=principal_scope,
        )

    def _transition(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        owner_id: str,
        allowed_statuses: frozenset[str],
        update_sql: str,
        update_args: tuple,
        new_status: IdempotencyStatus,
        now: datetime | None,
        idempotent_success_digest: str | None = None,
        completed_response: dict[str, Any] | None = None,
        already_completed_digest: str | None = None,
    ) -> TransitionResult:
        clean_key = _check_token(key, "key", self.limits.max_key_length)
        clean_op = _check_token(operation, "operation", self.limits.max_operation_length)
        clean_scope = _check_token(
            principal_scope, "principal_scope", self.limits.max_principal_scope_length
        )
        clean_fp = self._check_fingerprint(request_fingerprint)
        owner = _check_token(owner_id, "owner_id", self.limits.max_principal_scope_length)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) \
                or expected_generation < 1:
            raise IdempotencyStoreError("INPUT_INVALID", "expected_generation is invalid")
        moment = self._now(now)

        try:
            self._ensure_schema()
        except IdempotencyStoreError as exc:
            return self._transition_failure(exc, clean_key, clean_op, clean_scope)

        try:
            with self._transaction() as conn:
                row = conn.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM idempotency_records "
                    "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                    (clean_op, clean_scope, clean_key),
                ).fetchone()
                if row is None:
                    return TransitionResult(
                        decision="NOT_FOUND", reason_code="RECORD_NOT_FOUND",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                    )
                if not self._valid_row_status(row):
                    return TransitionResult(
                        decision="CORRUPT", reason_code="RECORD_CORRUPT",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                    )
                if row[3] != clean_fp:
                    return TransitionResult(
                        decision="CONFLICT", reason_code="FINGERPRINT_MISMATCH",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if row[10] != expected_generation:
                    return TransitionResult(
                        decision="STALE_GENERATION", reason_code="STALE_GENERATION",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if row[9] != owner:
                    return TransitionResult(
                        decision="WRONG_OWNER", reason_code="WRONG_OWNER",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if new_status == "COMPLETED" and row[4] == "COMPLETED":
                    if already_completed_digest is not None and row[14] == already_completed_digest:
                        return TransitionResult(
                            applied=True, decision="ALREADY_COMPLETED",
                            reason_code="IDEMPOTENT_COMPLETION",
                            key=clean_key, operation=clean_op, principal_scope=clean_scope,
                            status="COMPLETED", generation=row[10], run_id=row[8],
                            idempotent=True, response=completed_response,
                        )
                    return TransitionResult(
                        decision="CONFLICT", reason_code="COMPLETION_CONTENT_MISMATCH",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if row[4] not in allowed_statuses:
                    return TransitionResult(
                        decision="ILLEGAL_TRANSITION", reason_code="ILLEGAL_TRANSITION",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                conn.execute(update_sql, update_args + (clean_op, clean_scope, clean_key))
                return TransitionResult(
                    applied=True, decision="APPLIED", reason_code="APPLIED",
                    key=clean_key, operation=clean_op, principal_scope=clean_scope,
                    status=new_status, generation=row[10],
                    run_id=row[8], response=completed_response,
                )
        except sqlite3.OperationalError as exc:
            return self._transition_failure(
                IdempotencyStoreError("DATABASE_BUSY", str(exc)),
                clean_key, clean_op, clean_scope,
            )
        except sqlite3.DatabaseError as exc:
            return self._transition_failure(
                IdempotencyStoreError("DATABASE_CORRUPT", str(exc)),
                clean_key, clean_op, clean_scope,
            )
        except sqlite3.Error as exc:
            return self._transition_failure(
                IdempotencyStoreError("DATABASE_UNAVAILABLE", str(exc)),
                clean_key, clean_op, clean_scope,
            )

    def mark_running(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        owner_id: str,
        run_id: str,
        now: datetime | None = None,
    ) -> TransitionResult:
        clean_run = _check_token(run_id, "run_id", self.limits.max_principal_scope_length)
        moment = self._now(now)
        return self._transition(
            key=key, operation=operation, principal_scope=principal_scope,
            request_fingerprint=request_fingerprint, expected_generation=expected_generation,
            owner_id=owner_id, allowed_statuses=frozenset({"CLAIMED"}),
            update_sql=(
                "UPDATE idempotency_records SET status='IN_PROGRESS', run_id=?, updated_at=?, "
                "lease_expires_at=? WHERE operation=? AND principal_scope=? AND idempotency_key=?"
            ),
            update_args=(
                clean_run, _iso(moment),
                _iso(moment + timedelta(seconds=self.limits.lease_seconds)),
            ),
            new_status="IN_PROGRESS", now=moment,
        )

    def complete_success(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        owner_id: str,
        response: Mapping | Contract | None = None,
        now: datetime | None = None,
    ) -> TransitionResult:
        try:
            response_json, response_digest = _serialize_response(
                response, self.limits.max_response_bytes
            )
        except IdempotencyStoreError as exc:
            return TransitionResult(
                decision="REJECTED", reason_code=exc.code,
                key=key, operation=operation, principal_scope=principal_scope,
            )
        parsed = _parse_response(response_json)
        moment = self._now(now)
        # A repeated identical completion is resolved inside the transaction by
        # comparing the stored digest; a different digest conflicts.
        result = self._transition(
            key=key, operation=operation, principal_scope=principal_scope,
            request_fingerprint=request_fingerprint, expected_generation=expected_generation,
            owner_id=owner_id, allowed_statuses=frozenset({"CLAIMED", "IN_PROGRESS"}),
            update_sql=(
                "UPDATE idempotency_records SET status='COMPLETED', response_json=?, "
                "response_digest=?, error_class=NULL, updated_at=?, lease_expires_at=NULL "
                "WHERE operation=? AND principal_scope=? AND idempotency_key=?"
            ),
            update_args=(response_json, response_digest, _iso(moment)),
            new_status="COMPLETED", now=moment,
            completed_response=parsed, already_completed_digest=response_digest,
        )
        return result

    def complete_failure_retryable(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        owner_id: str,
        error_class: str,
        now: datetime | None = None,
    ) -> TransitionResult:
        return self._failure_completion(
            key=key, operation=operation, principal_scope=principal_scope,
            request_fingerprint=request_fingerprint, expected_generation=expected_generation,
            owner_id=owner_id, error_class=error_class, new_status="FAILED_RETRYABLE", now=now,
        )

    def complete_failure_final(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        owner_id: str,
        error_class: str,
        now: datetime | None = None,
    ) -> TransitionResult:
        return self._failure_completion(
            key=key, operation=operation, principal_scope=principal_scope,
            request_fingerprint=request_fingerprint, expected_generation=expected_generation,
            owner_id=owner_id, error_class=error_class, new_status="FAILED_FINAL", now=now,
        )

    def _failure_completion(
        self, *, key, operation, principal_scope, request_fingerprint,
        expected_generation, owner_id, error_class, new_status, now,
    ) -> TransitionResult:
        try:
            clean_error = _check_token(
                error_class, "error_class", self.limits.max_operation_length
            )
        except IdempotencyStoreError as exc:
            return TransitionResult(
                decision="REJECTED", reason_code=exc.code,
                key=key, operation=operation, principal_scope=principal_scope,
            )
        moment = self._now(now)
        return self._transition(
            key=key, operation=operation, principal_scope=principal_scope,
            request_fingerprint=request_fingerprint, expected_generation=expected_generation,
            owner_id=owner_id, allowed_statuses=frozenset({"CLAIMED", "IN_PROGRESS"}),
            update_sql=(
                "UPDATE idempotency_records SET status=?, error_class=?, response_json=NULL, "
                "response_digest=NULL, updated_at=?, lease_expires_at=NULL "
                "WHERE operation=? AND principal_scope=? AND idempotency_key=?"
            ),
            update_args=(new_status, clean_error, _iso(moment)),
            new_status=new_status, now=moment,
        )

    def expire_record(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        owner_id: str,
        now: datetime | None = None,
    ) -> TransitionResult:
        moment = self._now(now)
        return self._transition(
            key=key, operation=operation, principal_scope=principal_scope,
            request_fingerprint=request_fingerprint, expected_generation=expected_generation,
            owner_id=owner_id, allowed_statuses=frozenset({"CLAIMED", "IN_PROGRESS"}),
            update_sql=(
                "UPDATE idempotency_records SET status='EXPIRED', updated_at=?, "
                "lease_expires_at=NULL WHERE operation=? AND principal_scope=? AND idempotency_key=?"
            ),
            update_args=(_iso(moment),),
            new_status="EXPIRED", now=moment,
        )

    # -- replay / reads ------------------------------------------------------

    def read_result(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        now: datetime | None = None,
    ) -> ReadResult:
        clean_key = _check_token(key, "key", self.limits.max_key_length)
        clean_op = _check_token(operation, "operation", self.limits.max_operation_length)
        clean_scope = _check_token(
            principal_scope, "principal_scope", self.limits.max_principal_scope_length
        )
        moment = self._now(now)
        try:
            self._ensure_schema()
        except IdempotencyStoreError as exc:
            return ReadResult(found=False, reason_code=exc.code[:128] or "AUTHORITY_UNAVAILABLE")
        try:
            conn = self._connect()
            try:
                self._configure(conn)
                row = conn.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM idempotency_records "
                    "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                    (clean_op, clean_scope, clean_key),
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return ReadResult(found=False, reason_code="DATABASE_CORRUPT")
        except sqlite3.Error:
            return ReadResult(found=False, reason_code="DATABASE_UNAVAILABLE")
        if row is None:
            return ReadResult(found=False, reason_code="NOT_FOUND")
        if not self._valid_row_status(row):
            return ReadResult(found=True, reason_code="RECORD_CORRUPT")
        kind = row[4]
        expired = self._is_expired(moment, kind, row[7])
        response = _parse_response(row[13]) if kind == "COMPLETED" and not expired else None
        return ReadResult(
            found=True,
            reason_code="REPLAY" if kind == "COMPLETED" and not expired else kind,
            status=kind,
            generation=row[10],
            run_id=row[8],
            expired=expired,
            response=response,
        )

    def get_record(
        self, *, key: str, operation: str, principal_scope: str
    ) -> RecordView | None:
        clean_key = _check_token(key, "key", self.limits.max_key_length)
        clean_op = _check_token(operation, "operation", self.limits.max_operation_length)
        clean_scope = _check_token(
            principal_scope, "principal_scope", self.limits.max_principal_scope_length
        )
        self._ensure_schema()
        conn = self._connect()
        try:
            self._configure(conn)
            row = conn.execute(
                f"SELECT {_RECORD_COLUMNS} FROM idempotency_records "
                "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                (clean_op, clean_scope, clean_key),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return self._row_to_view(row)

    def recent_records(self, *, limit: int | None = None) -> tuple[RecordView, ...]:
        bound = self.limits.max_query_limit if limit is None else limit
        if not isinstance(bound, int) or isinstance(bound, bool) or bound < 1:
            raise IdempotencyStoreError("INPUT_INVALID", "limit is invalid")
        bound = min(bound, self.limits.max_query_limit)
        self._ensure_schema()
        conn = self._connect()
        try:
            self._configure(conn)
            rows = conn.execute(
                f"SELECT {_RECORD_COLUMNS} FROM idempotency_records "
                "ORDER BY updated_at DESC LIMIT ?",
                (bound,),
            ).fetchall()
        finally:
            conn.close()
        return tuple(self._row_to_view(row) for row in rows)

    def recovery_candidates(
        self, *, limit: int | None = None
    ) -> tuple[RecoveryCandidate, ...]:
        bound = self.limits.max_recovery_scan if limit is None else limit
        if not isinstance(bound, int) or isinstance(bound, bool) or bound < 1:
            raise IdempotencyStoreError("INPUT_INVALID", "limit is invalid")
        bound = min(bound, self.limits.max_recovery_scan)
        self._ensure_schema()
        conn = self._connect()
        try:
            self._configure(conn)
            rows = conn.execute(
                "SELECT operation, principal_scope, idempotency_key, status, generation, "
                "updated_at, expires_at, owner_id, run_id FROM idempotency_records "
                "WHERE status IN ('CLAIMED','IN_PROGRESS') ORDER BY updated_at ASC LIMIT ?",
                (bound,),
            ).fetchall()
        finally:
            conn.close()
        return tuple(
            RecoveryCandidate(
                operation=row[0], principal_scope=row[1], key=row[2], status=row[3],
                generation=row[4], updated_at=_parse_iso(row[5]), expires_at=_parse_iso(row[6]),
                owner_id=row[7], run_id=row[8],
            )
            for row in rows
            if row[3] in VALID_STATUSES
        )

    # -- recovery ------------------------------------------------------------

    def recover_abandoned_claim(
        self,
        *,
        key: str,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        lock_acquirable: bool,
        lease_expired: bool,
        now: datetime | None = None,
        new_owner_id_value: str | None = None,
        process_alive: bool | None = None,
    ) -> RecoveryResult:
        """Explicit, evidence-driven recovery. Never reclaims on time alone."""

        clean_key = _check_token(key, "key", self.limits.max_key_length)
        clean_op = _check_token(operation, "operation", self.limits.max_operation_length)
        clean_scope = _check_token(
            principal_scope, "principal_scope", self.limits.max_principal_scope_length
        )
        clean_fp = self._check_fingerprint(request_fingerprint)
        if not isinstance(expected_generation, int) or isinstance(expected_generation, bool) \
                or expected_generation < 1:
            raise IdempotencyStoreError("INPUT_INVALID", "expected_generation is invalid")
        moment = self._now(now)
        new_owner = self._owner(new_owner_id_value)

        try:
            self._ensure_schema()
        except IdempotencyStoreError as exc:
            return RecoveryResult(
                decision="AUTHORITY_UNAVAILABLE",
                reason_code=exc.code[:128] or "AUTHORITY_UNAVAILABLE",
                key=clean_key, operation=clean_op, principal_scope=clean_scope,
            )
        try:
            with self._transaction() as conn:
                row = conn.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM idempotency_records "
                    "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                    (clean_op, clean_scope, clean_key),
                ).fetchone()
                if row is None:
                    return RecoveryResult(
                        decision="NOT_FOUND", reason_code="RECORD_NOT_FOUND",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                    )
                if not self._valid_row_status(row):
                    return RecoveryResult(
                        decision="CORRUPT", reason_code="RECORD_CORRUPT",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                    )
                if row[3] != clean_fp or row[10] != expected_generation:
                    return RecoveryResult(
                        decision="GENERATION_MISMATCH", reason_code="STALE_EVIDENCE",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if row[4] in TERMINAL_STATUSES:
                    return RecoveryResult(
                        decision="TERMINAL", reason_code="TERMINAL_RECORD",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if row[4] not in ACTIVE_STATUSES:
                    return RecoveryResult(
                        decision="NOT_RECLAIMABLE", reason_code="NOT_ACTIVE",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if process_alive is True:
                    return RecoveryResult(
                        decision="NOT_RECLAIMABLE", reason_code="OWNER_ALIVE",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if not lock_acquirable:
                    return RecoveryResult(
                        decision="BLOCKED", reason_code="LOCK_HELD",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                if not lease_expired:
                    return RecoveryResult(
                        decision="BLOCKED", reason_code="LEASE_ACTIVE",
                        key=clean_key, operation=clean_op, principal_scope=clean_scope,
                        status=row[4], generation=row[10],
                    )
                generation = row[10] + 1
                conn.execute(
                    "UPDATE idempotency_records SET status='CLAIMED', owner_id=?, "
                    "generation=?, attempt_count=attempt_count+1, run_id=NULL, "
                    "response_json=NULL, response_digest=NULL, error_class=NULL, "
                    "updated_at=?, lease_expires_at=? "
                    "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                    (
                        new_owner, generation, _iso(moment),
                        _iso(moment + timedelta(seconds=self.limits.lease_seconds)),
                        clean_op, clean_scope, clean_key,
                    ),
                )
                return RecoveryResult(
                    decision="RECLAIMED", reason_code="RECLAIMED", reclaimed=True,
                    key=clean_key, operation=clean_op, principal_scope=clean_scope,
                    status="CLAIMED", generation=generation,
                )
        except sqlite3.OperationalError as exc:
            return RecoveryResult(
                decision="AUTHORITY_UNAVAILABLE", reason_code="DATABASE_BUSY",
                key=clean_key, operation=clean_op, principal_scope=clean_scope,
            )
        except sqlite3.DatabaseError:
            return RecoveryResult(
                decision="CORRUPT", reason_code="DATABASE_CORRUPT",
                key=clean_key, operation=clean_op, principal_scope=clean_scope,
            )
        except sqlite3.Error:
            return RecoveryResult(
                decision="AUTHORITY_UNAVAILABLE", reason_code="DATABASE_UNAVAILABLE",
                key=clean_key, operation=clean_op, principal_scope=clean_scope,
            )

    # -- retention / cleanup -------------------------------------------------

    def cleanup(self, *, now: datetime | None = None, batch: int | None = None) -> CleanupResult:
        moment = self._now(now)
        bound = self.limits.max_cleanup_batch if batch is None else batch
        if not isinstance(bound, int) or isinstance(bound, bool) or bound < 1:
            raise IdempotencyStoreError("INPUT_INVALID", "batch is invalid")
        bound = min(bound, self.limits.max_cleanup_batch)

        completed_cutoff = moment - timedelta(seconds=self.limits.completed_retention_seconds)
        failed_cutoff = moment - timedelta(seconds=self.limits.failed_retention_seconds)
        try:
            self._ensure_schema()
        except IdempotencyStoreError as exc:
            return CleanupResult(scanned=0, deleted=0, reason_code=exc.code[:128] or "UNAVAILABLE")
        try:
            with self._transaction() as conn:
                rows = conn.execute(
                    "SELECT operation, principal_scope, idempotency_key, status, updated_at "
                    "FROM idempotency_records "
                    "WHERE status IN ('COMPLETED','FAILED_RETRYABLE','FAILED_FINAL',"
                    "'EXPIRED','CONFLICT','CORRUPT') "
                    "ORDER BY updated_at ASC LIMIT ?",
                    (bound,),
                ).fetchall()
                deleted = 0
                for operation, scope, key, status, updated_at in rows:
                    cutoff = failed_cutoff if status in ("FAILED_RETRYABLE", "FAILED_FINAL") \
                        else completed_cutoff
                    if _parse_iso(updated_at) > cutoff:
                        continue
                    conn.execute(
                        "DELETE FROM idempotency_records "
                        "WHERE operation=? AND principal_scope=? AND idempotency_key=?",
                        (operation, scope, key),
                    )
                    deleted += 1
                return CleanupResult(scanned=len(rows), deleted=deleted)
        except sqlite3.OperationalError:
            return CleanupResult(scanned=0, deleted=0, reason_code="DATABASE_BUSY")
        except sqlite3.DatabaseError:
            return CleanupResult(scanned=0, deleted=0, reason_code="DATABASE_CORRUPT")
        except sqlite3.Error:
            return CleanupResult(scanned=0, deleted=0, reason_code="DATABASE_UNAVAILABLE")

    # -- integrity -----------------------------------------------------------

    def integrity_check(self, *, max_errors: int = 16) -> CorruptionReport:
        """Explicit, bounded integrity check. Not run automatically."""

        if not isinstance(max_errors, int) or isinstance(max_errors, bool) or max_errors < 1:
            raise IdempotencyStoreError("INPUT_INVALID", "max_errors is invalid")
        try:
            self._ensure_schema()
        except IdempotencyStoreError:
            return CorruptionReport(integrity_ok=False, errors=("SCHEMA_UNAVAILABLE",))
        conn = self._connect()
        try:
            self._configure(conn)
            rows = conn.execute("PRAGMA integrity_check(1)").fetchall()
        except sqlite3.DatabaseError:
            return CorruptionReport(integrity_ok=False, errors=("DATABASE_CORRUPT",))
        except sqlite3.Error:
            return CorruptionReport(integrity_ok=False, errors=("DATABASE_UNAVAILABLE",))
        finally:
            conn.close()
        messages = tuple(str(row[0]) for row in rows[:max_errors])
        ok = len(rows) == 1 and str(rows[0][0]) == "ok"
        return CorruptionReport(integrity_ok=ok, errors=() if ok else messages)


__all__ = [
    "ACTIVE_STATUSES",
    "ClaimDecision",
    "ClaimResult",
    "CleanupResult",
    "CorruptionReport",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "IdempotencyLimits",
    "IdempotencyStatus",
    "IdempotencyStoreError",
    "MonitoringTriggerIdempotencyStore",
    "ReadResult",
    "RecordView",
    "RecoveryCandidate",
    "RecoveryDecision",
    "RecoveryResult",
    "SCHEMA_VERSION",
    "TransitionDecision",
    "TransitionResult",
    "VALID_STATUSES",
    "new_owner_id",
]
