"""Restart-safe SQLite alert outbox/read model for Supervisor anomaly events.

Explicit-path, transactional, bounded and sanitized.  It never delivers any
external notification, never writes anomaly state, and never touches trading, MM
or Governance.  Each stored record links to the existing Phase 2 anomaly
fingerprint; this is an operational index, not a second anomaly-state authority.
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .monitoring_alert_models import (
    ALERT_FINGERPRINT_VERSION,
    ALERT_SCHEMA_VERSION,
    COOLDOWN_SECONDS,
    MAX_ALERT_PAGE,
    SEVERITY_RANK,
    AlertCandidate,
    AlertIngestResult,
    AlertPage,
    AlertRecord,
)
from .monitoring_models import aware

ALERT_FINGERPRINT_SALT = "supervisor-alert-id-v1"
MAX_STORED_BYTES = 16 * 1024
DEFAULT_MAX_RECORDS = 100000

_SCHEMA_VERSION_KEY = "schema_version"

_CREATE_META = "CREATE TABLE IF NOT EXISTS alert_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
_CREATE_ALERTS = (
    "CREATE TABLE IF NOT EXISTS alert_records ("
    "alert_id TEXT PRIMARY KEY, "
    "anomaly_fingerprint TEXT NOT NULL, "
    "episode_number INTEGER NOT NULL, "
    "status TEXT NOT NULL, "
    "current_severity TEXT NOT NULL, "
    "first_seen_at TEXT NOT NULL, "
    "last_seen_at TEXT NOT NULL, "
    "payload TEXT NOT NULL)"
)
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_alert_status ON alert_records(status)",
    "CREATE INDEX IF NOT EXISTS idx_alert_last_seen ON alert_records(last_seen_at)",
)


class AlertStoreError(Exception):
    """A bounded, presentation-safe alert-store failure with a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def deterministic_alert_id(candidate: AlertCandidate) -> str:
    """Deterministic, bounded alert id from the anomaly identity and episode."""

    payload = "|".join((
        ALERT_FINGERPRINT_VERSION,
        ALERT_FINGERPRINT_SALT,
        candidate.anomaly_fingerprint,
        candidate.policy_version,
        candidate.metric,
        candidate.metric_version,
        candidate.scope,
        candidate.mode,
        str(candidate.episode_number),
    ))
    return "A" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:31]


def _cooldown_for(severity: str) -> int:
    return COOLDOWN_SECONDS.get(severity, 0)


class MonitoringAlertStore:
    """Explicit-path bounded alert outbox.  Constructor performs no I/O."""

    def __init__(
        self,
        path: str | Path | None,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
        clock=None,
    ) -> None:
        if path is None or isinstance(path, bool):
            raise TypeError("an explicit alert database path is required")
        candidate = Path(path)
        if str(candidate).strip() in ("", "."):
            raise TypeError("an explicit alert database path is required")
        if not candidate.is_absolute():
            raise ValueError("the alert database path must be absolute")
        if not isinstance(max_records, int) or isinstance(max_records, bool) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self.path = candidate
        self.max_records = max_records
        self._clock = clock if clock is not None else _utcnow
        self._initialized = False

    # -- schema --------------------------------------------------------------

    def _validate_path(self, *, create_parent: bool) -> None:
        if self.path.is_symlink():
            raise AlertStoreError("PATH_SYMLINK_REJECTED")
        if self.path.exists():
            if not self.path.is_file():
                raise AlertStoreError("PATH_NOT_REGULAR")
            return
        parent = self.path.parent
        if parent.exists():
            if not parent.is_dir():
                raise AlertStoreError("PATH_NOT_DIRECTORY")
            return
        if create_parent:
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise AlertStoreError("PATH_PARENT_MISSING") from exc
            return
        raise AlertStoreError("PATH_PARENT_MISSING")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=2.0, isolation_level=None)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("PRAGMA busy_timeout=2000")
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

    def initialize(self, *, create_parent: bool = False) -> None:
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
            conn.execute(_CREATE_ALERTS)
            for statement in _CREATE_INDEXES:
                conn.execute(statement)
            row = conn.execute(
                "SELECT v FROM alert_meta WHERE k=?", (_SCHEMA_VERSION_KEY,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO alert_meta(k, v) VALUES(?, ?)",
                    (_SCHEMA_VERSION_KEY, ALERT_SCHEMA_VERSION),
                )
            elif row[0] != ALERT_SCHEMA_VERSION:
                conn.execute("ROLLBACK")
                raise AlertStoreError("SCHEMA_UNSUPPORTED")
            conn.execute("COMMIT")
        except AlertStoreError:
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
            raise AlertStoreError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self._initialized = True

    # -- serialization -------------------------------------------------------

    @staticmethod
    def _serialize(record: AlertRecord) -> str:
        try:
            text = record.stable_json()
        except Exception as exc:  # noqa: BLE001
            raise AlertStoreError("RECORD_INVALID") from exc
        if len(text.encode("utf-8")) > MAX_STORED_BYTES:
            raise AlertStoreError("RECORD_TOO_LARGE")
        return text

    @staticmethod
    def _deserialize(text: str) -> AlertRecord:
        try:
            return AlertRecord.model_validate_json(text)
        except Exception as exc:  # noqa: BLE001
            raise AlertStoreError("RECORD_CORRUPT") from exc

    # -- ingest --------------------------------------------------------------

    def ingest(self, candidate: AlertCandidate, *, now: datetime | None = None) -> AlertIngestResult:
        """Create/update/deduplicate one alert episode transactionally."""

        if not isinstance(candidate, AlertCandidate):
            return AlertIngestResult(decision="INVALID", reason_code="CANDIDATE_INVALID")
        moment = aware(now) if now is not None else aware(self._clock())
        alert_id = deterministic_alert_id(candidate)
        try:
            self._ensure_schema()
        except AlertStoreError as exc:
            return AlertIngestResult(alert_id=alert_id, decision="INVALID", reason_code=exc.code)

        try:
            with self._transaction() as conn:
                row = conn.execute(
                    "SELECT payload FROM alert_records WHERE alert_id=?", (alert_id,)
                ).fetchone()
                existing = None
                if row is not None:
                    try:
                        existing = self._deserialize(row[0])
                    except AlertStoreError:
                        existing = None
                if existing is None:
                    total = conn.execute("SELECT COUNT(*) FROM alert_records").fetchone()[0]
                    if total >= self.max_records:
                        return AlertIngestResult(
                            alert_id=alert_id, decision="INVALID",
                            reason_code="CAPACITY_EXHAUSTED",
                        )
                    record = self._new_record(candidate, alert_id, moment)
                    conn.execute(
                        "INSERT INTO alert_records(alert_id, anomaly_fingerprint, episode_number, "
                        "status, current_severity, first_seen_at, last_seen_at, payload) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (record.alert_id, record.anomaly_fingerprint, record.episode_number,
                         record.status, record.current_severity,
                         record.first_seen_at.isoformat(), record.last_seen_at.isoformat(),
                         self._serialize(record)),
                    )
                    return AlertIngestResult(
                        alert_id=alert_id, decision="CREATED", reason_code="ALERT_CREATED",
                        created_count=1, delivery_status=record.delivery_status,
                    )
                decision, record = self._merge(existing, candidate, moment)
                if decision != "UPDATED":
                    return AlertIngestResult(
                        alert_id=alert_id, decision=decision,  # type: ignore[arg-type]
                        reason_code=decision, suppressed_count=1,
                        delivery_status=existing.delivery_status,
                    )
                conn.execute(
                    "UPDATE alert_records SET status=?, current_severity=?, last_seen_at=?, payload=? "
                    "WHERE alert_id=?",
                    (record.status, record.current_severity, record.last_seen_at.isoformat(),
                     self._serialize(record), alert_id),
                )
                return AlertIngestResult(
                    alert_id=alert_id, decision="UPDATED", reason_code="ALERT_UPDATED",
                    updated_count=1, delivery_status=record.delivery_status,
                )
        except sqlite3.OperationalError as exc:
            return AlertIngestResult(alert_id=alert_id, decision="INVALID", reason_code="DATABASE_BUSY")
        except sqlite3.Error:
            return AlertIngestResult(alert_id=alert_id, decision="INVALID", reason_code="DATABASE_UNAVAILABLE")

    def _new_record(self, candidate: AlertCandidate, alert_id: str, moment: datetime) -> AlertRecord:
        cooldown = _cooldown_for(candidate.severity)
        return AlertRecord(
            alert_id=alert_id,
            anomaly_fingerprint=candidate.anomaly_fingerprint,
            episode_number=candidate.episode_number,
            status="OPEN",
            delivery_status="NOT_CONFIGURED",
            current_severity=candidate.severity,
            highest_severity=candidate.severity,
            category=candidate.category,
            metric=candidate.metric,
            metric_version=candidate.metric_version,
            policy_version=candidate.policy_version,
            scope=candidate.scope,
            mode=candidate.mode,
            symbol=candidate.symbol,
            observation_id=candidate.observation_id,
            source_revision=candidate.source_revision,
            reason_codes=candidate.reason_codes,
            provenance=candidate.provenance,
            freshness=candidate.freshness,
            availability=candidate.availability,
            partial_result=candidate.partial_result,
            occurrence_count=1,
            first_seen_at=moment,
            last_seen_at=moment,
            cooldown_until=moment + timedelta(seconds=cooldown) if cooldown else None,
        )

    def _merge(
        self, existing: AlertRecord, candidate: AlertCandidate, moment: datetime
    ) -> tuple[str, AlertRecord]:
        if existing.status == "RESOLVED":
            return "SUPPRESSED_RESOLVED", existing
        if existing.status == "ACKNOWLEDGED" and existing.acknowledged_at is not None:
            if SEVERITY_RANK.get(candidate.severity, 0) <= SEVERITY_RANK.get(existing.current_severity, 0):
                return "SUPPRESSED_ACKNOWLEDGED", existing
        if existing.cooldown_until is not None and moment < existing.cooldown_until:
            if SEVERITY_RANK.get(candidate.severity, 0) <= SEVERITY_RANK.get(existing.current_severity, 0):
                return "SUPPRESSED_COOLDOWN", existing
        highest = max(
            (existing.highest_severity, candidate.severity),
            key=lambda value: SEVERITY_RANK.get(value, 0),
        )
        cooldown = _cooldown_for(candidate.severity)
        updated = existing.model_copy(update={
            "current_severity": candidate.severity,
            "highest_severity": highest,
            "occurrence_count": existing.occurrence_count + 1,
            "last_seen_at": moment,
            "observation_id": candidate.observation_id,
            "source_revision": candidate.source_revision,
            "reason_codes": tuple(sorted(set(existing.reason_codes) | set(candidate.reason_codes))),
            "provenance": tuple(sorted(set(existing.provenance) | set(candidate.provenance))),
            "freshness": candidate.freshness,
            "availability": candidate.availability,
            "partial_result": candidate.partial_result,
            "cooldown_until": moment + timedelta(seconds=cooldown) if cooldown else None,
        })
        return "UPDATED", updated

    # -- acknowledgement / resolution (no API endpoint in this task) ---------

    def acknowledge(self, alert_id: str, *, now: datetime | None = None) -> bool:
        return self._set_status(alert_id, "ACKNOWLEDGED", now)

    def resolve(self, alert_id: str, *, now: datetime | None = None) -> bool:
        return self._set_status(alert_id, "RESOLVED", now)

    def _set_status(self, alert_id: str, status: str, now: datetime | None) -> bool:
        moment = aware(now) if now is not None else aware(self._clock())
        try:
            self._ensure_schema()
            with self._transaction() as conn:
                row = conn.execute(
                    "SELECT payload FROM alert_records WHERE alert_id=?", (alert_id,)
                ).fetchone()
                if row is None:
                    return False
                record = self._deserialize(row[0])
                update: dict[str, Any] = {"status": status}
                if status == "ACKNOWLEDGED":
                    update["acknowledged_at"] = moment
                else:
                    update["resolved_at"] = moment
                updated = record.model_copy(update=update)
                conn.execute(
                    "UPDATE alert_records SET status=?, payload=? WHERE alert_id=?",
                    (status, self._serialize(updated), alert_id),
                )
                return True
        except AlertStoreError:
            return False
        except sqlite3.Error:
            return False

    # -- reads ---------------------------------------------------------------

    def get(self, alert_id: str) -> AlertRecord | None:
        try:
            self._ensure_schema()
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload FROM alert_records WHERE alert_id=?", (alert_id,)
                ).fetchone()
            finally:
                conn.close()
        except AlertStoreError:
            return None
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            return self._deserialize(row[0])
        except AlertStoreError:
            return None

    @staticmethod
    def _cursor(alert_id: str, last_seen_at: str) -> str:
        raw = f"{last_seen_at}|{alert_id}".encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode(value: str) -> tuple[str, str]:
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
            last_seen_at, alert_id = raw.split("|", 1)
            return last_seen_at, alert_id
        except Exception as exc:  # noqa: BLE001
            raise AlertStoreError("CURSOR_INVALID") from exc

    def list(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        status: str | None = None,
    ) -> AlertPage:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_ALERT_PAGE:
            raise AlertStoreError("INPUT_INVALID")
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status=?")
            args.append(status)
        if cursor:
            last_seen_at, alert_id = self._decode(cursor)
            clauses.append("(last_seen_at, alert_id) < (?, ?)")
            args.extend([last_seen_at, alert_id])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        self._ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT alert_id, last_seen_at, payload FROM alert_records"
                f"{where} ORDER BY last_seen_at DESC, alert_id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
        except sqlite3.Error as exc:
            raise AlertStoreError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()
        records: list[AlertRecord] = []
        corrupt = 0
        for row in rows[:limit]:
            try:
                records.append(self._deserialize(row[2]))
            except AlertStoreError:
                corrupt += 1
        next_cursor = self._cursor(rows[limit - 1][0], rows[limit - 1][1]) if len(rows) > limit else None
        return AlertPage(
            alerts=tuple(records), next_cursor=next_cursor,
            corruption_count=corrupt, partial_result=corrupt > 0,
        )

    def count(self, *, status: str | None = None) -> int:
        self._ensure_schema()
        conn = self._connect()
        try:
            if status:
                return int(conn.execute(
                    "SELECT COUNT(*) FROM alert_records WHERE status=?", (status,)
                ).fetchone()[0])
            return int(conn.execute("SELECT COUNT(*) FROM alert_records").fetchone()[0])
        except sqlite3.Error as exc:
            raise AlertStoreError("DATABASE_UNAVAILABLE") from exc
        finally:
            conn.close()

    def recover(self, *, limit: int = 100) -> AlertPage:
        """Bounded restart recovery of open alerts; isolates corrupt rows."""

        return self.list(limit=min(limit, MAX_ALERT_PAGE), status="OPEN")


__all__ = [
    "ALERT_FINGERPRINT_SALT",
    "AlertStoreError",
    "DEFAULT_MAX_RECORDS",
    "MAX_STORED_BYTES",
    "MonitoringAlertStore",
    "deterministic_alert_id",
]
