"""Preview-first ChatGPT export refresh.

The preview opens the store read-only. It never creates a database, a table, a
checkpoint row, an observation row, or a knowledge record. It never moves or
deletes the export and never returns raw conversation bodies or secrets.
"""

from __future__ import annotations

from pathlib import Path
import time

from ..chatgpt_import.account import AccountError, resolve_account
from ..chatgpt_import.models import STATUS_OK as PARSE_OK
from ..chatgpt_import.parser import parse_export
from .checkpoint import (
    read_existing_state_from_path,
    read_latest_observations_from_path,
)
from .export_diff import diff_export
from .export_identity import ExportIdentityError, build_export_identity
from .models import (
    LIMIT_EXCEEDED,
    STATUS_ERROR,
    STATUS_OK,
    TIMESTAMP_REQUIRED,
    SyncLimits,
    SyncPreview,
)


def preview_export_sync(
    source: str | Path | bytes,
    account_alias: str,
    *,
    store_path: str | Path | None,
    observed_at: str,
    limits: SyncLimits | None = None,
    clock=None,
) -> SyncPreview:
    settings = limits or SyncLimits()
    started = (clock or time.monotonic)()
    if not observed_at or not isinstance(observed_at, str):
        return _empty_preview(account_alias, TIMESTAMP_REQUIRED)
    try:
        account = resolve_account(account_alias)
    except AccountError as exc:
        return _empty_preview(account_alias, exc.code)
    parsed = parse_export(source, account.alias, settings.import_limits)
    if parsed.status != PARSE_OK:
        return _empty_preview(account.alias, parsed.error or "INVALID_EXPORT", parsed.export_format)
    try:
        identity = build_export_identity(parsed, account.alias, observed_at)
    except ExportIdentityError as exc:
        return _empty_preview(account.alias, exc.code, parsed.export_format)

    existing = (
        read_existing_state_from_path(store_path, account.alias)
        if store_path is not None
        else _empty_state()
    )
    observations = (
        read_latest_observations_from_path(store_path, account.alias)
        if store_path is not None
        else {}
    )
    diff = diff_export(
        parsed,
        account.alias,
        existing=existing,
        latest_observations=observations,
        observed_at=observed_at,
        limits=settings,
    )
    if diff.status != STATUS_OK:
        return _empty_preview(account.alias, diff.error or "UNSUPPORTED_FORMAT", identity.export_format)

    elapsed = (clock or time.monotonic)() - started
    if settings.max_scan_seconds > 0 and elapsed > settings.max_scan_seconds:
        return _empty_preview(account.alias, LIMIT_EXCEEDED, identity.export_format)
    if diff.estimated_database_growth_bytes > settings.max_database_growth_bytes:
        return _empty_preview(account.alias, LIMIT_EXCEEDED, identity.export_format)

    entries = tuple(
        entry.to_dict() for entry in diff.entries[: max(settings.max_preview_entries, 0)]
    )
    return SyncPreview(
        status=STATUS_OK,
        account_alias=account.alias,
        export_identity=identity,
        export_format=identity.export_format,
        conversation_count=identity.conversation_count,
        message_count=identity.message_count,
        new_conversation_count=diff.new_conversation_count,
        new_message_count=diff.new_message_count,
        updated_message_count=diff.updated_message_count,
        unchanged_message_count=diff.unchanged_message_count,
        missing_conversation_count=diff.missing_conversation_count,
        reappeared_conversation_count=diff.reappeared_conversation_count,
        review_required_count=diff.review_required_count,
        secret_rejected_count=diff.secret_rejected_count,
        out_of_scope_count=diff.out_of_scope_count,
        graph_change_count=diff.graph_change_count,
        estimated_database_growth_bytes=diff.estimated_database_growth_bytes,
        entries=entries,
    )


def _empty_state():
    from .models import ExistingChatGPTState

    return ExistingChatGPTState(frozenset(), {})


def _empty_preview(
    account_alias: str,
    error: str,
    export_format: str = "UNKNOWN",
) -> SyncPreview:
    return SyncPreview(
        status=STATUS_ERROR,
        account_alias=str(account_alias or ""),
        export_identity=None,
        export_format=export_format,
        conversation_count=0,
        message_count=0,
        new_conversation_count=0,
        new_message_count=0,
        updated_message_count=0,
        unchanged_message_count=0,
        missing_conversation_count=0,
        reappeared_conversation_count=0,
        review_required_count=0,
        secret_rejected_count=0,
        out_of_scope_count=0,
        graph_change_count=0,
        estimated_database_growth_bytes=0,
        entries=(),
        error=error,
    )
