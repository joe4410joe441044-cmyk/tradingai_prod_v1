"""Dry-run import preview.

The preview never creates a database and never writes a row. It reports only
counts and byte estimates. Raw conversation text is not returned.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
from urllib.parse import quote

from ..knowledge_store import logical_key, version_id
from .account import AccountError, resolve_account
from .adapter import build_items
from .models import (
    IN_SCOPE,
    OUT_OF_SCOPE,
    PRIVACY_REVIEW,
    REVIEW_REQUIRED,
    STATUS_ERROR,
    STATUS_OK,
    UNKNOWN,
    ImportLimits,
    ImportPreview,
)
from .parser import parse_export
from .pipeline import evaluate_conversations


_PREVIEW_TIMESTAMP = "PREVIEW_NO_WRITE"


def preview_export(
    source: str | Path | bytes,
    account_alias: str,
    *,
    store_path: str | Path | None = None,
    limits: ImportLimits | None = None,
) -> ImportPreview:
    try:
        account = resolve_account(account_alias)
    except AccountError as exc:
        return _empty_preview(STATUS_ERROR, str(account_alias or ""), exc.code)
    parsed = parse_export(source, account.alias, limits)
    if parsed.status != STATUS_OK:
        return _empty_preview(STATUS_ERROR, account.alias, parsed.error or "INVALID_EXPORT", parsed.export_format, parsed.source_export_id)
    evaluations = evaluate_conversations(parsed.conversations)
    in_scope = sum(1 for item in evaluations if item.relevance.status == IN_SCOPE)
    out_of_scope = sum(1 for item in evaluations if item.relevance.status == OUT_OF_SCOPE)
    review = sum(
        1
        for item in evaluations
        if item.relevance.status == REVIEW_REQUIRED or item.privacy.status == PRIVACY_REVIEW
    )
    unknown = sum(1 for item in evaluations if item.relevance.status == UNKNOWN)
    secrets = sum(1 for item in evaluations if item.privacy.status == PRIVACY_REVIEW)
    candidates = tuple(item for item in evaluations if item.importable)
    items, _ = build_items(candidates, collected_at=_PREVIEW_TIMESTAMP, limits=limits)
    existing = _existing_state(store_path)
    new_count = updated_count = duplicate_count = 0
    growth = 0
    seen: set[str] = set()
    for item in items:
        digest = item.content_hash or hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        record_id = version_id(item, digest)
        key = logical_key(item)
        if record_id in seen or (existing is not None and record_id in existing.record_ids):
            duplicate_count += 1
        elif existing is not None and key in existing.by_logical:
            updated_count += 1
            growth += _growth(item)
        else:
            new_count += 1
            growth += _growth(item)
        seen.add(record_id)
    return ImportPreview(
        status=STATUS_OK,
        account_alias=account.alias,
        export_format=parsed.export_format,
        source_export_id=parsed.source_export_id,
        conversation_count=len(parsed.conversations),
        message_count=len(evaluations),
        in_scope_count=in_scope,
        out_of_scope_count=out_of_scope,
        review_required_count=review,
        unknown_count=unknown,
        secret_flag_count=secrets,
        duplicate_count=duplicate_count,
        new_record_count=new_count,
        updated_record_count=updated_count,
        estimated_database_growth_bytes=growth,
    )


class _Existing:
    def __init__(self, record_ids: set[str], by_logical: dict[str, set[str]]) -> None:
        self.record_ids = record_ids
        self.by_logical = by_logical


def _existing_state(store_path: str | Path | None) -> _Existing | None:
    if store_path is None or str(store_path) == "":
        return None
    target = Path(store_path)
    if target.is_symlink() or not target.exists() or not target.is_file():
        return None
    uri = "file:" + quote(target.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT record_id, logical_key FROM records WHERE source_type=?",
            ("CHATGPT_EXPORT",),
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
    return _Existing(record_ids, by_logical)


def _growth(item) -> int:
    return len(item.content.encode("utf-8")) + len(item.title.encode("utf-8")) + 512


def _empty_preview(
    status: str,
    account_alias: str,
    error: str,
    export_format: str = "UNKNOWN",
    source_export_id: str | None = None,
) -> ImportPreview:
    return ImportPreview(
        status=status,
        account_alias=account_alias,
        export_format=export_format,
        source_export_id=source_export_id,
        conversation_count=0,
        message_count=0,
        in_scope_count=0,
        out_of_scope_count=0,
        review_required_count=0,
        unknown_count=0,
        secret_flag_count=0,
        duplicate_count=0,
        new_record_count=0,
        updated_record_count=0,
        estimated_database_growth_bytes=0,
        error=error,
    )
