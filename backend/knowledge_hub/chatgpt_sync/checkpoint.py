"""Additive ChatGPT export checkpoint and observation persistence.

Two tables are added to an existing BC-3 store:

* ``chatgpt_sync_checkpoints`` keeps one refresh state per account alias.
* ``chatgpt_sync_observations`` keeps an append-only history of missing,
  reappeared, and branch-graph changes.

Neither table changes the BC-3 ``records`` schema or its ``user_version``. A
checkpoint and its observations are written inside the same transaction as the
knowledge records, so a failed import cannot advance the checkpoint alone.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from ..knowledge_store import StoreError
from .models import ExistingChatGPTState, ExistingMessage


_SCHEMA = """
CREATE TABLE IF NOT EXISTS chatgpt_sync_checkpoints (
    account_alias TEXT PRIMARY KEY,
    last_export_hash TEXT NOT NULL,
    last_import_status TEXT NOT NULL,
    last_imported_at TEXT NOT NULL,
    last_observed_at TEXT,
    export_format TEXT,
    last_message_count INTEGER NOT NULL,
    last_conversation_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chatgpt_sync_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_alias TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    status TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    export_hash TEXT,
    message_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_chatgpt_obs_account
    ON chatgpt_sync_observations(account_alias, conversation_id, status);
"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_SCHEMA)


def _connect(path: str | Path, *, read_only: bool) -> sqlite3.Connection | None:
    target = Path(path)
    if target.is_symlink() or not target.exists() or not target.is_file():
        return None
    if read_only:
        uri = "file:" + quote(target.absolute().as_posix(), safe="/:") + "?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=2.0)
        except sqlite3.Error:
            return None
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=2000")
        except sqlite3.Error:
            connection.close()
            return None
        return connection
    try:
        connection = sqlite3.connect(str(target), timeout=2.0)
    except sqlite3.Error:
        return None
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=2000")
        connection.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        connection.close()
        return None
    return connection


def open_read_only(store_path: str | Path) -> sqlite3.Connection | None:
    return _connect(store_path, read_only=True)


def open_read_write(store_path: str | Path) -> sqlite3.Connection:
    connection = _connect(store_path, read_only=False)
    if connection is None:
        raise StoreError("STORE_NOT_AVAILABLE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'"
        ).fetchone()
    except sqlite3.Error:
        connection.close()
        raise StoreError("STORE_NOT_AVAILABLE") from None
    if version != 1 or table is None:
        connection.close()
        raise StoreError("STORE_NOT_AVAILABLE")
    return connection


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def read_checkpoint(connection: sqlite3.Connection, account_alias: str) -> dict | None:
    try:
        if not _has_table(connection, "chatgpt_sync_checkpoints"):
            return None
        row = connection.execute(
            "SELECT * FROM chatgpt_sync_checkpoints WHERE account_alias=?",
            (account_alias,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else dict(row)


def read_latest_observations(connection: sqlite3.Connection, account_alias: str) -> dict[str, str]:
    try:
        if not _has_table(connection, "chatgpt_sync_observations"):
            return {}
        rows = connection.execute(
            """
            SELECT observations.conversation_id, observations.status
            FROM chatgpt_sync_observations AS observations
            JOIN (
                SELECT conversation_id, MAX(id) AS latest_id
                FROM chatgpt_sync_observations
                WHERE account_alias=?
                GROUP BY conversation_id
            ) AS latest ON latest.latest_id = observations.id
            """,
            (account_alias,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {row["conversation_id"]: row["status"] for row in rows}


def read_existing_state(connection: sqlite3.Connection, account_alias: str) -> ExistingChatGPTState:
    try:
        if not _has_table(connection, "records"):
            return ExistingChatGPTState(frozenset(), {})
        rows = connection.execute(
            """
            SELECT conversation_id, message_id, content_hash, metadata_json
            FROM records
            WHERE source_type='CHATGPT_EXPORT' AND source_account=? AND presence='CURRENT'
            """,
            (account_alias,),
        ).fetchall()
    except sqlite3.Error:
        return ExistingChatGPTState(frozenset(), {})
    conversations: set[str] = set()
    messages: dict[tuple[str, str], ExistingMessage] = {}
    for row in rows:
        conversation_id = row["conversation_id"]
        if not isinstance(conversation_id, str) or conversation_id == "":
            continue
        conversations.add(conversation_id)
        message_id = row["message_id"]
        if not isinstance(message_id, str) or message_id == "":
            continue
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        messages[(conversation_id, message_id)] = ExistingMessage(
            content_hash=str(row["content_hash"] or ""),
            parent_message_id=str(metadata.get("parent_message_id") or ""),
            branch_identity=str(metadata.get("branch_identity") or ""),
            role=str(metadata.get("role") or ""),
        )
    return ExistingChatGPTState(frozenset(conversations), messages)


def read_existing_state_from_path(
    store_path: str | Path,
    account_alias: str,
) -> ExistingChatGPTState:
    connection = open_read_only(store_path)
    if connection is None:
        return ExistingChatGPTState(frozenset(), {})
    try:
        return read_existing_state(connection, account_alias)
    finally:
        connection.close()


def read_latest_observations_from_path(
    store_path: str | Path,
    account_alias: str,
) -> dict[str, str]:
    connection = open_read_only(store_path)
    if connection is None:
        return {}
    try:
        return read_latest_observations(connection, account_alias)
    finally:
        connection.close()


def read_checkpoint_from_path(store_path: str | Path, account_alias: str) -> dict | None:
    connection = open_read_only(store_path)
    if connection is None:
        return None
    try:
        return read_checkpoint(connection, account_alias)
    finally:
        connection.close()


def write_checkpoint(connection: sqlite3.Connection, row: dict) -> None:
    connection.execute(
        """
        INSERT INTO chatgpt_sync_checkpoints (
            account_alias, last_export_hash, last_import_status,
            last_imported_at, last_observed_at, export_format,
            last_message_count, last_conversation_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_alias) DO UPDATE SET
            last_export_hash=excluded.last_export_hash,
            last_import_status=excluded.last_import_status,
            last_imported_at=excluded.last_imported_at,
            last_observed_at=excluded.last_observed_at,
            export_format=excluded.export_format,
            last_message_count=excluded.last_message_count,
            last_conversation_count=excluded.last_conversation_count
        """,
        (
            row["account_alias"],
            row["last_export_hash"],
            row["last_import_status"],
            row["last_imported_at"],
            row.get("last_observed_at"),
            row.get("export_format"),
            int(row.get("last_message_count") or 0),
            int(row.get("last_conversation_count") or 0),
        ),
    )


def append_observations(connection: sqlite3.Connection, rows: tuple[dict, ...]) -> int:
    if not rows:
        return 0
    connection.executemany(
        """
        INSERT INTO chatgpt_sync_observations (
            account_alias, conversation_id, status, observed_at, export_hash, message_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["account_alias"],
                row["conversation_id"],
                row["status"],
                row["observed_at"],
                row.get("export_hash"),
                row.get("message_id"),
            )
            for row in rows
        ],
    )
    return len(rows)
