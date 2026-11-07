"""Adapt classified ChatGPT messages into existing BC-3 store items."""

from __future__ import annotations

from dataclasses import dataclass

from ..knowledge_store import KnowledgeStore, StoreItem
from ..security import secret_bytes
from .models import Evaluation, ImportLimits, Message


SOURCE_TYPE = "CHATGPT_EXPORT"
RECORD_TYPE = "CHATGPT_MESSAGE"
ACCESS_SCOPE = "OPERATOR"
TRUST = "UNTRUSTED_KNOWLEDGE"
UNKNOWN = "UNKNOWN"


class ItemRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CommitResult:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0


def source_identifier(message: Message) -> str:
    return f"chatgpt/{message.account_alias}/{message.conversation_id}/{message.message_id}"


def build_item(evaluation: Evaluation, *, collected_at: str) -> StoreItem:
    message = evaluation.message
    title = _title(message)
    content = message.content
    if secret_bytes(title.encode("utf-8")) or secret_bytes(content.encode("utf-8")):
        raise ItemRejected("SECRET_EXCLUDED")
    metadata = {
        "access_scope": ACCESS_SCOPE,
        "trust": TRUST,
        "authority": "NONE",
        "historical": "true",
        "account_alias": message.account_alias,
        "conversation_title": message.conversation_title,
        "conversation_created_at": message.conversation_created_at,
        "conversation_updated_at": message.conversation_updated_at,
        "message_created_at": message.message_created_at,
        "parent_message_id": message.parent_message_id or "",
        "branch_identity": message.branch_identity,
        "source_export_id": message.source_export_id,
        "role": message.role,
        "relevance_status": evaluation.relevance.status,
        "relevance_reason": evaluation.relevance.reason,
        "privacy_status": evaluation.privacy.status,
    }
    return StoreItem(
        source_type=SOURCE_TYPE,
        source_identifier=source_identifier(message),
        record_type=RECORD_TYPE,
        title=title,
        content=content,
        content_hash=message.content_hash,
        collected_at=collected_at,
        verification_state="COLLECTED",
        truth_kind="HISTORICAL_CONTEXT",
        source_timestamp=None if message.message_created_at == UNKNOWN else message.message_created_at,
        source_account=message.account_alias,
        conversation_id=message.conversation_id,
        message_id=message.message_id,
        metadata=metadata,
    )


def build_items(
    evaluations: tuple[Evaluation, ...],
    *,
    collected_at: str,
    limits: ImportLimits | None = None,
) -> tuple[tuple[StoreItem, ...], tuple[str, ...]]:
    del limits
    items: list[StoreItem] = []
    rejected: list[str] = []
    for evaluation in evaluations:
        try:
            items.append(build_item(evaluation, collected_at=collected_at))
        except ItemRejected as exc:
            rejected.append(exc.code)
    return tuple(items), tuple(rejected)


def commit_items(
    store: KnowledgeStore,
    items: tuple[StoreItem, ...],
    *,
    indexed_at: str,
    scan_scope: str = "chatgpt-import",
) -> CommitResult:
    """Write inside one transaction. Any store failure rolls the batch back."""

    inserted = skipped = superseded = 0

    def action() -> CommitResult:
        nonlocal inserted, skipped, superseded
        for item in items:
            state = store.upsert(item, indexed_at=indexed_at, scan_scope=scan_scope)
            if state == "SKIPPED":
                skipped += 1
            elif state == "SUPERSEDED":
                inserted += 1
                superseded += 1
            else:
                inserted += 1
        return CommitResult(inserted=inserted, skipped=skipped, superseded=superseded)

    return store.in_transaction(action)


def _title(message: Message) -> str:
    base = f"{message.conversation_title} | {message.role} | {message.message_id}"
    return base[:300]
