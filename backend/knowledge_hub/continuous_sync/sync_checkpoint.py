"""Checkpoint persistence and read-only store inspection.

Checkpoints live in an additive table in the same SQLite file as the BC-3
knowledge store. The BC-3 schema version and records table are not changed.
A checkpoint is written only after its source has been imported successfully.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from urllib.parse import quote

from ..knowledge_store import StoreError
from .models import ExistingState


_CHECKPOINT_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_checkpoints (
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    branch TEXT,
    last_seen_commit TEXT,
    last_scan_at TEXT NOT NULL,
    report_path TEXT,
    report_content_hash TEXT,
    last_imported_version TEXT,
    source_agent TEXT,
    PRIMARY KEY (source_kind, source_id)
);
"""


class CheckpointStore:
    def __init__(self, connection: sqlite3.Connection, path: Path) -> None:
        self._connection = connection
        self._path = path
        self._closed = False

    @classmethod
    def open(cls, store_path: str | Path) -> "CheckpointStore":
        target = Path(store_path)
        if target.is_symlink() or not target.is_file():
            raise StoreError("STORE_NOT_FOUND")
        try:
            connection = sqlite3.connect(str(target), timeout=2.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                connection.close()
                raise StoreError("SCHEMA_MISMATCH")
            connection.executescript(_CHECKPOINT_SCHEMA)
            connection.commit()
        except StoreError:
            raise
        except sqlite3.Error:
            raise StoreError("DATABASE_ERROR") from None
        return cls(connection, target)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def load(self, source_kind: str, source_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM sync_checkpoints WHERE source_kind=? AND source_id=?",
            (source_kind, source_id),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def load_all(self) -> dict[tuple[str, str], dict]:
        rows = self._connection.execute("SELECT * FROM sync_checkpoints").fetchall()
        return {(row["source_kind"], row["source_id"]): dict(row) for row in rows}

    def known_commits(self) -> frozenset[str]:
        rows = self._connection.execute(
            "SELECT DISTINCT commit_sha FROM records WHERE source_type='GIT_COMMIT' "
            "AND commit_sha IS NOT NULL LIMIT 100000"
        ).fetchall()
        return frozenset(row[0] for row in rows if row[0])

    def save_many(self, checkpoints: tuple[dict, ...] | list[dict]) -> None:
        if not checkpoints:
            return
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            for row in checkpoints:
                self._connection.execute(
                    """
                    INSERT INTO sync_checkpoints (
                        source_kind, source_id, branch, last_seen_commit,
                        last_scan_at, report_path, report_content_hash,
                        last_imported_version, source_agent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_kind, source_id) DO UPDATE SET
                        branch=excluded.branch,
                        last_seen_commit=excluded.last_seen_commit,
                        last_scan_at=excluded.last_scan_at,
                        report_path=excluded.report_path,
                        report_content_hash=excluded.report_content_hash,
                        last_imported_version=excluded.last_imported_version,
                        source_agent=excluded.source_agent
                    """,
                    (
                        row["source_kind"],
                        row["source_id"],
                        row.get("branch"),
                        row.get("last_seen_commit"),
                        row["last_scan_at"],
                        row.get("report_path"),
                        row.get("report_content_hash"),
                        row.get("last_imported_version"),
                        row.get("source_agent"),
                    ),
                )
            self._connection.commit()
        except sqlite3.Error:
            self._connection.rollback()
            raise StoreError("CHECKPOINT_WRITE_FAILED") from None


def _read_only_connection(store_path: str | Path) -> sqlite3.Connection | None:
    target = Path(store_path)
    if target.is_symlink() or not target.is_file():
        return None
    uri = "file:" + quote(target.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error:
        return None
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def read_existing_state(store_path: str | Path) -> ExistingState | None:
    target = Path(store_path)
    if str(store_path) == "" or target.is_symlink() or not target.exists() or not target.is_file():
        return None
    connection = _read_only_connection(target)
    if connection is None:
        return None
    try:
        rows = connection.execute(
            "SELECT record_id, logical_key FROM records WHERE source_type IN "
            "('GIT_COMMIT','GIT_WORKTREE','CURSOR_REPORT','VSCODE_REPORT','DEVELOPMENT_REPORT')"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    record_ids: set[str] = set()
    by_logical: dict[str, set[str]] = {}
    for row in rows:
        record_ids.add(row["record_id"])
        by_logical.setdefault(row["logical_key"], set()).add(row["record_id"])
    return ExistingState(
        record_ids=frozenset(record_ids),
        by_logical={key: frozenset(value) for key, value in by_logical.items()},
    )


def read_checkpoints(store_path: str | Path) -> dict[tuple[str, str], dict]:
    target = Path(store_path)
    if str(store_path) == "" or target.is_symlink() or not target.exists() or not target.is_file():
        return {}
    connection = _read_only_connection(target)
    if connection is None:
        return {}
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_checkpoints'"
        ).fetchone()
        if table is None:
            return {}
        rows = connection.execute("SELECT * FROM sync_checkpoints").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return {(row["source_kind"], row["source_id"]): dict(row) for row in rows}


def read_known_commits(store_path: str | Path) -> frozenset[str]:
    target = Path(store_path)
    if str(store_path) == "" or target.is_symlink() or not target.exists() or not target.is_file():
        return frozenset()
    connection = _read_only_connection(target)
    if connection is None:
        return frozenset()
    try:
        rows = connection.execute(
            "SELECT DISTINCT commit_sha FROM records WHERE source_type='GIT_COMMIT' "
            "AND commit_sha IS NOT NULL LIMIT 100000"
        ).fetchall()
    except sqlite3.Error:
        return frozenset()
    finally:
        connection.close()
    return frozenset(row[0] for row in rows if row[0])
