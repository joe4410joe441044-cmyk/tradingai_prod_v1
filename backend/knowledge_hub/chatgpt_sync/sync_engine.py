"""Approved, atomic ChatGPT export refresh.

The engine reuses the BC-5 parser, classifiers, item builder, and commit path.
It reuses the BC-3 store and the BC-6 checkpoint design. There is no daemon,
timer, cron entry, scheduler registration, ChatGPT login, or network call.
Knowledge records, the refresh checkpoint, and the observation history are
committed in one SQLite transaction; a failure leaves all three unchanged.
"""

from __future__ import annotations

from pathlib import Path

from ..chatgpt_import.account import AccountError, resolve_account
from ..chatgpt_import.adapter import commit_items
from ..chatgpt_import.models import STATUS_OK as PARSE_OK
from ..chatgpt_import.parser import parse_export
from ..knowledge_store import KnowledgeStore, StoreError, StoreLimits
from .approval_gate import ApprovalError, validate_approval
from .checkpoint import (
    append_observations,
    ensure_schema,
    open_read_write,
    read_checkpoint_from_path,
    read_existing_state,
    read_latest_observations,
    write_checkpoint,
)
from .export_diff import diff_export, importable_items
from .export_identity import ExportIdentityError, build_export_identity
from .models import (
    EXPORT_STATE_CHANGED,
    EXPORT_STATE_UNCHANGED,
    LIMIT_EXCEEDED,
    PARTIAL_IMPORT_ROLLED_BACK,
    SECRET_REVIEW_REQUIRED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    TIMESTAMP_REQUIRED,
    Approval,
    ExportIdentity,
    SyncLimits,
    SyncPreview,
    SyncReport,
)


def _error_report(
    account_alias: str,
    error: str,
    *,
    export_content_hash: str | None = None,
    export_state: str | None = None,
) -> SyncReport:
    return SyncReport(
        status=STATUS_ERROR,
        account_alias=str(account_alias or ""),
        export_content_hash=export_content_hash,
        export_state=export_state,
        inserted=0,
        skipped=0,
        superseded=0,
        rejected=0,
        new_conversation_count=0,
        new_message_count=0,
        updated_message_count=0,
        missing_conversation_count=0,
        reappeared_conversation_count=0,
        graph_change_count=0,
        checkpoint_updated=False,
        observations_recorded=0,
        estimated_database_growth_bytes=0,
        errors=(error,),
    )


def _unchanged_report(account_alias: str, identity: ExportIdentity) -> SyncReport:
    return SyncReport(
        status=STATUS_OK,
        account_alias=account_alias,
        export_content_hash=identity.export_content_hash,
        export_state=EXPORT_STATE_UNCHANGED,
        inserted=0,
        skipped=0,
        superseded=0,
        rejected=0,
        new_conversation_count=0,
        new_message_count=0,
        updated_message_count=0,
        missing_conversation_count=0,
        reappeared_conversation_count=0,
        graph_change_count=0,
        checkpoint_updated=False,
        observations_recorded=0,
        estimated_database_growth_bytes=0,
    )


def sync_export(
    source: str | Path | bytes,
    account_alias: str,
    store_path: str | Path,
    *,
    observed_at: str,
    indexed_at: str,
    preview: SyncPreview | None = None,
    approval: Approval | None = None,
    limits: SyncLimits | None = None,
    scan_scope: str = "chatgpt-sync",
) -> SyncReport:
    settings = limits or SyncLimits()
    if not observed_at or not isinstance(observed_at, str):
        return _error_report(account_alias, TIMESTAMP_REQUIRED)
    if not indexed_at or not isinstance(indexed_at, str):
        return _error_report(account_alias, TIMESTAMP_REQUIRED)
    if store_path is None or str(store_path) == "":
        return _error_report(account_alias, "STORE_NOT_AVAILABLE")
    try:
        account = resolve_account(account_alias)
    except AccountError as exc:
        return _error_report(account_alias, exc.code)

    parsed = parse_export(source, account.alias, settings.import_limits)
    if parsed.status != PARSE_OK:
        return _error_report(account.alias, parsed.error or "INVALID_EXPORT")
    try:
        identity = build_export_identity(parsed, account.alias, observed_at)
    except ExportIdentityError as exc:
        return _error_report(account.alias, exc.code)

    try:
        validate_approval(
            approval,
            preview=preview,
            account_alias=account.alias,
            export_content_hash=identity.export_content_hash,
            store_path=store_path,
        )
    except ApprovalError as exc:
        return _error_report(
            account.alias,
            exc.code,
            export_content_hash=identity.export_content_hash,
            export_state=EXPORT_STATE_CHANGED,
        )

    previous = read_checkpoint_from_path(store_path, account.alias)
    if (
        previous is not None
        and previous.get("last_export_hash") == identity.export_content_hash
        and previous.get("last_import_status") == STATUS_OK
    ):
        return _unchanged_report(account.alias, identity)

    try:
        connection = open_read_write(store_path)
    except StoreError as exc:
        return _error_report(
            account.alias,
            exc.code,
            export_content_hash=identity.export_content_hash,
        )
    store = None
    try:
        ensure_schema(connection)
        existing = read_existing_state(connection, account.alias)
        observations = read_latest_observations(connection, account.alias)
        diff = diff_export(
            parsed,
            account.alias,
            existing=existing,
            latest_observations=observations,
            observed_at=observed_at,
            limits=settings,
        )
        if diff.status != STATUS_OK:
            return _error_report(
                account.alias,
                diff.error or "UNSUPPORTED_FORMAT",
                export_content_hash=identity.export_content_hash,
            )
        if diff.estimated_database_growth_bytes > settings.max_database_growth_bytes:
            return _error_report(
                account.alias,
                LIMIT_EXCEEDED,
                export_content_hash=identity.export_content_hash,
            )
        items, rejected_codes = importable_items(parsed, observed_at=indexed_at)
        final_status = (
            STATUS_PARTIAL
            if diff.secret_rejected_count or rejected_codes
            else STATUS_OK
        )
        checkpoint_row = {
            "account_alias": account.alias,
            "last_export_hash": identity.export_content_hash,
            "last_import_status": final_status,
            "last_imported_at": indexed_at,
            "last_observed_at": observed_at,
            "export_format": identity.export_format,
            "last_message_count": identity.message_count,
            "last_conversation_count": identity.conversation_count,
        }
        observation_rows = tuple(
            {
                "account_alias": entry.account_alias,
                "conversation_id": entry.conversation_id,
                "status": entry.status,
                "observed_at": observed_at,
                "export_hash": identity.export_content_hash,
                "message_id": entry.message_id,
            }
            for entry in diff.observations
        )
        store = KnowledgeStore(connection, StoreLimits())

        def action():
            committed = commit_items(
                store,
                items,
                indexed_at=indexed_at,
                scan_scope=f"{scan_scope}:{account.alias}",
            )
            write_checkpoint(connection, checkpoint_row)
            recorded = append_observations(connection, observation_rows)
            return committed, recorded

        committed, recorded = store.in_transaction(action)
    except StoreError:
        return _error_report(
            account.alias,
            PARTIAL_IMPORT_ROLLED_BACK,
            export_content_hash=identity.export_content_hash,
            export_state=EXPORT_STATE_CHANGED,
        )
    except Exception:
        return _error_report(
            account.alias,
            PARTIAL_IMPORT_ROLLED_BACK,
            export_content_hash=identity.export_content_hash,
            export_state=EXPORT_STATE_CHANGED,
        )
    finally:
        if store is not None:
            store.close()
        else:
            connection.close()

    errors: list[str] = []
    if final_status == STATUS_PARTIAL:
        errors.append(SECRET_REVIEW_REQUIRED)
    return SyncReport(
        status=final_status,
        account_alias=account.alias,
        export_content_hash=identity.export_content_hash,
        export_state=EXPORT_STATE_CHANGED,
        inserted=committed.inserted,
        skipped=committed.skipped,
        superseded=committed.superseded,
        rejected=diff.secret_rejected_count + len(rejected_codes),
        new_conversation_count=diff.new_conversation_count,
        new_message_count=diff.new_message_count,
        updated_message_count=diff.updated_message_count,
        missing_conversation_count=diff.missing_conversation_count,
        reappeared_conversation_count=diff.reappeared_conversation_count,
        graph_change_count=diff.graph_change_count,
        checkpoint_updated=True,
        observations_recorded=recorded,
        estimated_database_growth_bytes=diff.estimated_database_growth_bytes,
        errors=tuple(errors),
        rejected_codes=rejected_codes,
    )
