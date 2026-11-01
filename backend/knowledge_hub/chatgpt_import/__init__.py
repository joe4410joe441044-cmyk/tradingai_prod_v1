"""Isolated importer for two explicit ChatGPT accounts.

No import in this package performs a network call, contacts ChatGPT, runs a
collector, writes a database, or mutates runtime state.
"""

from .account import AccountError, AccountIdentity, resolve_account
from .adapter import CommitResult, build_item, build_items, commit_items
from .importer import import_export
from .models import (
    IN_SCOPE,
    OUT_OF_SCOPE,
    PRIVACY_CLEAN,
    PRIVACY_REVIEW,
    REVIEW_REQUIRED,
    STATUS_ERROR,
    STATUS_OK,
    UNKNOWN,
    Conversation,
    Evaluation,
    ImportLimits,
    ImportPreview,
    ImportReport,
    Message,
    ParseResult,
    PrivacyResult,
    RelevanceResult,
)
from .parser import parse_export
from .preview import preview_export
from .zip_security import ZipSecurityError, read_conversations_json


__all__ = [
    "AccountError",
    "AccountIdentity",
    "CommitResult",
    "Conversation",
    "Evaluation",
    "ImportLimits",
    "ImportPreview",
    "ImportReport",
    "IN_SCOPE",
    "Message",
    "OUT_OF_SCOPE",
    "PRIVACY_CLEAN",
    "PRIVACY_REVIEW",
    "ParseResult",
    "PrivacyResult",
    "REVIEW_REQUIRED",
    "RelevanceResult",
    "STATUS_ERROR",
    "STATUS_OK",
    "UNKNOWN",
    "ZipSecurityError",
    "build_item",
    "build_items",
    "commit_items",
    "import_export",
    "parse_export",
    "preview_export",
    "read_conversations_json",
    "resolve_account",
]
