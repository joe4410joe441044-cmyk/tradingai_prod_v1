"""Value objects for the isolated ChatGPT export importer.

Importing this package does not read an account, contact a network, or create
a database. All bounds are explicit and callers may narrow them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STATUS_OK = "OK"
STATUS_ERROR = "ERROR"

IN_SCOPE = "IN_SCOPE"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
UNKNOWN = "UNKNOWN"

PRIVACY_CLEAN = "CLEAN"
PRIVACY_REVIEW = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class ImportLimits:
    max_zip_bytes: int = 32 * 1024 * 1024
    max_uncompressed_bytes: int = 128 * 1024 * 1024
    max_entries: int = 128
    max_compression_ratio: int = 100
    max_json_bytes: int = 64 * 1024 * 1024
    max_conversations: int = 2_000
    max_messages: int = 200_000
    max_message_bytes: int = 200_000


@dataclass(frozen=True)
class Message:
    account_alias: str
    conversation_id: str
    conversation_title: str
    conversation_created_at: str
    conversation_updated_at: str
    message_id: str
    role: str
    message_created_at: str
    parent_message_id: str | None
    branch_identity: str
    content: str
    content_hash: str
    source_export_id: str


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class ParseResult:
    status: str
    export_format: str
    source_export_id: str | None
    conversations: tuple[Conversation, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class RelevanceResult:
    status: str
    reason: str
    matched: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "matched": list(self.matched)}


@dataclass(frozen=True)
class PrivacyResult:
    status: str
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "flags": list(self.flags)}


@dataclass(frozen=True)
class Evaluation:
    conversation: Conversation
    message: Message
    relevance: RelevanceResult
    privacy: PrivacyResult

    @property
    def importable(self) -> bool:
        return self.relevance.status == IN_SCOPE and self.privacy.status == PRIVACY_CLEAN


@dataclass(frozen=True)
class ImportPreview:
    status: str
    account_alias: str
    export_format: str
    source_export_id: str | None
    conversation_count: int
    message_count: int
    in_scope_count: int
    out_of_scope_count: int
    review_required_count: int
    unknown_count: int
    secret_flag_count: int
    duplicate_count: int
    new_record_count: int
    updated_record_count: int
    estimated_database_growth_bytes: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "account_alias": self.account_alias,
            "export_format": self.export_format,
            "source_export_id": self.source_export_id,
            "conversation_count": self.conversation_count,
            "message_count": self.message_count,
            "in_scope_count": self.in_scope_count,
            "out_of_scope_count": self.out_of_scope_count,
            "review_required_count": self.review_required_count,
            "unknown_count": self.unknown_count,
            "secret_flag_count": self.secret_flag_count,
            "duplicate_count": self.duplicate_count,
            "new_record_count": self.new_record_count,
            "updated_record_count": self.updated_record_count,
            "estimated_database_growth_bytes": self.estimated_database_growth_bytes,
            "error": self.error,
        }


@dataclass(frozen=True)
class ImportReport:
    status: str
    account_alias: str
    export_format: str
    source_export_id: str | None
    conversation_count: int
    message_count: int
    in_scope_count: int
    out_of_scope_count: int
    review_required_count: int
    unknown_count: int
    secret_flag_count: int
    inserted: int
    skipped: int
    superseded: int
    rejected: int
    error: str | None = None
    rejected_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "account_alias": self.account_alias,
            "export_format": self.export_format,
            "source_export_id": self.source_export_id,
            "conversation_count": self.conversation_count,
            "message_count": self.message_count,
            "in_scope_count": self.in_scope_count,
            "out_of_scope_count": self.out_of_scope_count,
            "review_required_count": self.review_required_count,
            "unknown_count": self.unknown_count,
            "secret_flag_count": self.secret_flag_count,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "superseded": self.superseded,
            "rejected": self.rejected,
            "error": self.error,
            "rejected_codes": list(self.rejected_codes),
        }
