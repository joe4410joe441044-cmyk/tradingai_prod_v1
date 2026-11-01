"""Explicit import of one synthetic or approved ChatGPT export."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from ..knowledge_store import KnowledgeStore, StoreError
from .account import AccountError, resolve_account
from .adapter import build_items, commit_items
from .models import (
    IN_SCOPE,
    OUT_OF_SCOPE,
    PRIVACY_REVIEW,
    REVIEW_REQUIRED,
    STATUS_ERROR,
    STATUS_OK,
    UNKNOWN,
    ImportLimits,
    ImportReport,
)
from .parser import parse_export
from .pipeline import evaluate_conversations


def import_export(
    source: str | Path | bytes,
    account_alias: str,
    store: KnowledgeStore,
    *,
    indexed_at: str,
    scan_scope: str = "chatgpt-import",
    limits: ImportLimits | None = None,
) -> ImportReport:
    if not indexed_at:
        return _error_report(account_alias, "TIMESTAMP_REQUIRED")
    try:
        account = resolve_account(account_alias)
    except AccountError as exc:
        return _error_report(account_alias, exc.code)
    parsed = parse_export(source, account.alias, limits)
    if parsed.status != STATUS_OK:
        return ImportReport(
            status=STATUS_ERROR,
            account_alias=account.alias,
            export_format=parsed.export_format,
            source_export_id=parsed.source_export_id,
            conversation_count=0,
            message_count=0,
            in_scope_count=0,
            out_of_scope_count=0,
            review_required_count=0,
            unknown_count=0,
            secret_flag_count=0,
            inserted=0,
            skipped=0,
            superseded=0,
            rejected=0,
            error=parsed.error,
        )
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
    items, rejected_codes = build_items(candidates, collected_at=indexed_at, limits=limits)
    rejected = len(evaluations) - len(items)
    try:
        committed = commit_items(store, items, indexed_at=indexed_at, scan_scope=scan_scope)
    except (StoreError, sqlite3.Error) as exc:
        code = exc.code if isinstance(exc, StoreError) else "DATABASE_ERROR"
        return ImportReport(
            status=STATUS_ERROR,
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
            inserted=0,
            skipped=0,
            superseded=0,
            rejected=rejected,
            error=code,
            rejected_codes=rejected_codes,
        )
    return ImportReport(
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
        inserted=committed.inserted,
        skipped=committed.skipped,
        superseded=committed.superseded,
        rejected=rejected,
        rejected_codes=rejected_codes,
    )


def _error_report(account_alias: str, error: str) -> ImportReport:
    return ImportReport(
        status=STATUS_ERROR,
        account_alias=str(account_alias or ""),
        export_format=UNKNOWN,
        source_export_id=None,
        conversation_count=0,
        message_count=0,
        in_scope_count=0,
        out_of_scope_count=0,
        review_required_count=0,
        unknown_count=0,
        secret_flag_count=0,
        inserted=0,
        skipped=0,
        superseded=0,
        rejected=0,
        error=error,
    )
