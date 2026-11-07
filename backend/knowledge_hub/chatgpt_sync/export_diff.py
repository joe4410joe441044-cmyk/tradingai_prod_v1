"""Incremental comparison of one ChatGPT export against the knowledge store.

Message identity is ``(account_alias, conversation_id, message_id)``. Content
hashes detect edited messages; parent, branch, and role metadata detect branch
graph changes that a content hash alone would miss. A conversation that is not
present in the newest export is observed as ``MISSING_FROM_EXPORT`` and is
never deleted. A conversation that returns is observed as ``REAPPEARED``.
"""

from __future__ import annotations

from ..chatgpt_import.adapter import ItemRejected, build_item
from ..chatgpt_import.models import (
    OUT_OF_SCOPE as OUT_OF_SCOPE_VALUE,
    PRIVACY_CLEAN as PRIVACY_CLEAN_VALUE,
    REVIEW_REQUIRED as REVIEW_VALUE,
    UNKNOWN as UNKNOWN_VALUE,
)
from ..chatgpt_import.models import ParseResult
from ..chatgpt_import.pipeline import evaluate_conversations
from .models import (
    GRAPH_CHANGED,
    MISSING_FROM_EXPORT,
    NEW_CONVERSATION,
    NEW_MESSAGE,
    OUT_OF_SCOPE,
    REAPPEARED,
    REJECTED_SECRET,
    REVIEW_REQUIRED as REVIEW_STATUS,
    STATUS_OK,
    UNCHANGED_MESSAGE,
    UPDATED_MESSAGE,
    DiffEntry,
    ExistingChatGPTState,
    ExportDiff,
    SyncLimits,
)


_PREVIEW_TIMESTAMP = "PREVIEW_NO_WRITE"


def _message_state(conversation_id: str, message_id: str) -> tuple[str, str]:
    return (conversation_id, message_id)


def diff_export(
    parsed: ParseResult,
    account_alias: str,
    *,
    existing: ExistingChatGPTState,
    latest_observations: dict[str, str],
    observed_at: str,
    limits: SyncLimits,
) -> ExportDiff:
    del limits
    if parsed.status != STATUS_OK:
        return _error_diff(parsed.error or "UNSUPPORTED_FORMAT")

    evaluations = evaluate_conversations(parsed.conversations)
    conversation_ids = tuple(conversation.conversation_id for conversation in parsed.conversations)
    known_conversations = existing.conversations
    new_conversation_ids = tuple(
        dict.fromkeys(
            conversation_id
            for conversation_id in conversation_ids
            if conversation_id not in known_conversations
        )
    )
    missing_conversation_ids = tuple(sorted(set(known_conversations) - set(conversation_ids)))
    reappeared_conversation_ids = tuple(
        conversation_id
        for conversation_id in dict.fromkeys(conversation_ids)
        if latest_observations.get(conversation_id) == MISSING_FROM_EXPORT
    )

    entries: list[DiffEntry] = []
    observations: list[DiffEntry] = []
    new_messages = updated = unchanged = review = secrets = out_of_scope = 0
    graph_changes = 0
    growth = 0

    for conversation_id in new_conversation_ids:
        entries.append(
            DiffEntry(
                status=NEW_CONVERSATION,
                account_alias=account_alias,
                conversation_id=conversation_id,
            )
        )

    for conversation_id in missing_conversation_ids:
        entry = DiffEntry(
            status=MISSING_FROM_EXPORT,
            account_alias=account_alias,
            conversation_id=conversation_id,
        )
        entries.append(entry)
        observations.append(entry)

    for conversation_id in reappeared_conversation_ids:
        entry = DiffEntry(
            status=REAPPEARED,
            account_alias=account_alias,
            conversation_id=conversation_id,
        )
        entries.append(entry)
        observations.append(entry)

    for evaluation in evaluations:
        conversation_id = evaluation.conversation.conversation_id
        message = evaluation.message
        if evaluation.relevance.status == OUT_OF_SCOPE_VALUE:
            out_of_scope += 1
            entries.append(
                DiffEntry(
                    status=OUT_OF_SCOPE,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                    reason=evaluation.relevance.reason,
                )
            )
            continue
        if evaluation.relevance.status in {REVIEW_VALUE, UNKNOWN_VALUE}:
            review += 1
            entries.append(
                DiffEntry(
                    status=REVIEW_STATUS,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                    reason=evaluation.relevance.reason,
                )
            )
            continue
        if evaluation.privacy.status != PRIVACY_CLEAN_VALUE:
            secrets += 1
            entries.append(
                DiffEntry(
                    status=REJECTED_SECRET,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                    reason="PRIVACY_REVIEW",
                )
            )
            continue
        try:
            item = build_item(evaluation, collected_at=observed_at or _PREVIEW_TIMESTAMP)
        except ItemRejected:
            secrets += 1
            entries.append(
                DiffEntry(
                    status=REJECTED_SECRET,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                    reason="SECRET_EXCLUDED",
                )
            )
            continue

        previous = existing.messages.get(_message_state(conversation_id, message.message_id))
        if previous is None:
            new_messages += 1
            growth += _item_size(item)
            entries.append(
                DiffEntry(
                    status=NEW_MESSAGE,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                )
            )
            continue

        parent = message.parent_message_id or ""
        graph_changed = (
            previous.parent_message_id != parent
            or previous.branch_identity != message.branch_identity
            or previous.role != message.role
        )
        content_changed = previous.content_hash != message.content_hash
        if content_changed or graph_changed:
            updated += 1
            if content_changed:
                growth += _item_size(item)
            if graph_changed:
                graph_changes += 1
                observations.append(
                    DiffEntry(
                        status=GRAPH_CHANGED,
                        account_alias=account_alias,
                        conversation_id=conversation_id,
                        message_id=message.message_id,
                        content_hash=message.content_hash,
                        previous_content_hash=previous.content_hash,
                        graph_changed=True,
                        reason="PARENT_OR_BRANCH_CHANGED",
                    )
                )
            entries.append(
                DiffEntry(
                    status=UPDATED_MESSAGE,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                    previous_content_hash=previous.content_hash,
                    graph_changed=graph_changed,
                )
            )
        else:
            unchanged += 1
            entries.append(
                DiffEntry(
                    status=UNCHANGED_MESSAGE,
                    account_alias=account_alias,
                    conversation_id=conversation_id,
                    message_id=message.message_id,
                    content_hash=message.content_hash,
                    previous_content_hash=previous.content_hash,
                )
            )

    return ExportDiff(
        status=STATUS_OK,
        new_conversation_count=len(new_conversation_ids),
        new_message_count=new_messages,
        updated_message_count=updated,
        unchanged_message_count=unchanged,
        missing_conversation_count=len(missing_conversation_ids),
        reappeared_conversation_count=len(reappeared_conversation_ids),
        review_required_count=review,
        secret_rejected_count=secrets,
        out_of_scope_count=out_of_scope,
        graph_change_count=graph_changes,
        estimated_database_growth_bytes=growth,
        new_conversation_ids=new_conversation_ids,
        missing_conversation_ids=missing_conversation_ids,
        reappeared_conversation_ids=reappeared_conversation_ids,
        entries=tuple(entries),
        observations=tuple(observations),
    )


def importable_items(parsed: ParseResult, *, observed_at: str) -> tuple[tuple, tuple[str, ...]]:
    """Build BC-5 store items for every importable message."""

    if parsed.status != STATUS_OK:
        return (), ()
    pieces = []
    rejected: list[str] = []
    for evaluation in evaluate_conversations(parsed.conversations):
        if not evaluation.importable:
            continue
        try:
            pieces.append(build_item(evaluation, collected_at=observed_at))
        except ItemRejected as exc:
            rejected.append(exc.code)
    return tuple(pieces), tuple(rejected)


def _item_size(item) -> int:
    return len(item.content.encode("utf-8")) + len(item.title.encode("utf-8")) + 512


def _error_diff(error: str) -> ExportDiff:
    return ExportDiff(
        status="ERROR",
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
        error=error,
    )
