"""Value objects for the ChatGPT export refresh synchronizer.

Importing this package performs no network call, no ChatGPT login, no browser
automation, no database write, and no scheduler registration. Every bound is
explicit and every write requires an approved export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..chatgpt_import.models import ImportLimits


SYNC_SCHEMA_VERSION = "tradingai-chatgpt-export-sync/v1"

STATUS_OK = "OK"
STATUS_ERROR = "ERROR"
STATUS_PARTIAL = "PARTIAL"

EXPORT_STATE_UNCHANGED = "EXPORT_UNCHANGED"
EXPORT_STATE_CHANGED = "EXPORT_CHANGED"

# Message / conversation observation states.
NEW_CONVERSATION = "NEW_CONVERSATION"
NEW_MESSAGE = "NEW_MESSAGE"
UPDATED_MESSAGE = "UPDATED_MESSAGE"
UNCHANGED_MESSAGE = "UNCHANGED_MESSAGE"
MISSING_FROM_EXPORT = "MISSING_FROM_EXPORT"
REAPPEARED = "REAPPEARED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
REJECTED_SECRET = "REJECTED_SECRET"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
GRAPH_CHANGED = "GRAPH_CHANGED"

# Failure codes.
INVALID_ZIP = "INVALID_ZIP"
ACCOUNT_ALIAS_REQUIRED = "ACCOUNT_ALIAS_REQUIRED"
INVALID_ACCOUNT_ALIAS = "INVALID_ACCOUNT_ALIAS"
ZIP_SECURITY_REJECTED = "ZIP_SECURITY_REJECTED"
SECRET_REVIEW_REQUIRED = "SECRET_REVIEW_REQUIRED"
PREVIEW_REQUIRED = "PREVIEW_REQUIRED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
APPROVAL_MISMATCH = "APPROVAL_MISMATCH"
STORE_NOT_AVAILABLE = "STORE_NOT_AVAILABLE"
STORE_WRITE_FAILED = "STORE_WRITE_FAILED"
CHECKPOINT_FAILED = "CHECKPOINT_FAILED"
PARTIAL_IMPORT_ROLLED_BACK = "PARTIAL_IMPORT_ROLLED_BACK"
LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
TIMESTAMP_REQUIRED = "TIMESTAMP_REQUIRED"


@dataclass(frozen=True)
class SyncLimits:
    """Import bounds plus refresh-specific bounds.

    The nested ``import_limits`` are the BC-5 ZIP, conversation, and message
    bounds. They are reused unchanged.
    """

    import_limits: ImportLimits = field(default_factory=ImportLimits)
    max_database_growth_bytes: int = 5_000_000
    max_preview_entries: int = 100
    max_import_batch_size: int = 200
    max_scan_seconds: float = 10.0


@dataclass(frozen=True)
class ExportIdentity:
    account_alias: str
    export_content_hash: str
    export_format: str
    export_observed_at: str
    conversation_count: int
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_alias": self.account_alias,
            "export_content_hash": self.export_content_hash,
            "export_format": self.export_format,
            "export_observed_at": self.export_observed_at,
            "conversation_count": self.conversation_count,
            "message_count": self.message_count,
        }


@dataclass(frozen=True)
class ExistingMessage:
    content_hash: str
    parent_message_id: str
    branch_identity: str
    role: str


@dataclass(frozen=True)
class ExistingChatGPTState:
    conversations: frozenset[str]
    messages: dict[tuple[str, str], ExistingMessage]


@dataclass(frozen=True)
class DiffEntry:
    status: str
    account_alias: str
    conversation_id: str
    message_id: str | None = None
    content_hash: str | None = None
    previous_content_hash: str | None = None
    graph_changed: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "account_alias": self.account_alias,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "content_hash": self.content_hash,
            "previous_content_hash": self.previous_content_hash,
            "graph_changed": self.graph_changed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExportDiff:
    status: str
    new_conversation_count: int
    new_message_count: int
    updated_message_count: int
    unchanged_message_count: int
    missing_conversation_count: int
    reappeared_conversation_count: int
    review_required_count: int
    secret_rejected_count: int
    out_of_scope_count: int
    graph_change_count: int
    estimated_database_growth_bytes: int
    new_conversation_ids: tuple[str, ...] = ()
    missing_conversation_ids: tuple[str, ...] = ()
    reappeared_conversation_ids: tuple[str, ...] = ()
    entries: tuple[DiffEntry, ...] = ()
    observations: tuple[DiffEntry, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class SyncPreview:
    status: str
    account_alias: str
    export_identity: ExportIdentity | None
    export_format: str
    conversation_count: int
    message_count: int
    new_conversation_count: int
    new_message_count: int
    updated_message_count: int
    unchanged_message_count: int
    missing_conversation_count: int
    reappeared_conversation_count: int
    review_required_count: int
    secret_rejected_count: int
    out_of_scope_count: int
    graph_change_count: int
    estimated_database_growth_bytes: int
    entries: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    @property
    def export_content_hash(self) -> str | None:
        return None if self.export_identity is None else self.export_identity.export_content_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "account_alias": self.account_alias,
            "export_identity": None if self.export_identity is None else self.export_identity.to_dict(),
            "export_format": self.export_format,
            "conversation_count": self.conversation_count,
            "message_count": self.message_count,
            "new_conversation_count": self.new_conversation_count,
            "new_message_count": self.new_message_count,
            "updated_message_count": self.updated_message_count,
            "unchanged_message_count": self.unchanged_message_count,
            "missing_conversation_count": self.missing_conversation_count,
            "reappeared_conversation_count": self.reappeared_conversation_count,
            "review_required_count": self.review_required_count,
            "secret_rejected_count": self.secret_rejected_count,
            "out_of_scope_count": self.out_of_scope_count,
            "graph_change_count": self.graph_change_count,
            "estimated_database_growth_bytes": self.estimated_database_growth_bytes,
            "entries": [dict(entry) for entry in self.entries],
            "error": self.error,
        }


@dataclass(frozen=True)
class Approval:
    account_alias: str
    export_content_hash: str
    store_path: str
    approved_at: str
    approved_by: str = "OPERATOR"


@dataclass(frozen=True)
class SyncReport:
    status: str
    account_alias: str
    export_content_hash: str | None
    export_state: str | None
    inserted: int
    skipped: int
    superseded: int
    rejected: int
    new_conversation_count: int
    new_message_count: int
    updated_message_count: int
    missing_conversation_count: int
    reappeared_conversation_count: int
    graph_change_count: int
    checkpoint_updated: bool
    observations_recorded: int
    estimated_database_growth_bytes: int
    errors: tuple[str, ...] = ()
    rejected_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "account_alias": self.account_alias,
            "export_content_hash": self.export_content_hash,
            "export_state": self.export_state,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "superseded": self.superseded,
            "rejected": self.rejected,
            "new_conversation_count": self.new_conversation_count,
            "new_message_count": self.new_message_count,
            "updated_message_count": self.updated_message_count,
            "missing_conversation_count": self.missing_conversation_count,
            "reappeared_conversation_count": self.reappeared_conversation_count,
            "graph_change_count": self.graph_change_count,
            "checkpoint_updated": self.checkpoint_updated,
            "observations_recorded": self.observations_recorded,
            "estimated_database_growth_bytes": self.estimated_database_growth_bytes,
            "errors": list(self.errors),
            "rejected_codes": list(self.rejected_codes),
        }
