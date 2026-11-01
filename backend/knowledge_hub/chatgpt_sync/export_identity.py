"""Export generation identity.

The content hash identifies one exported ``conversations.json`` document. It is
derived from the archive payload, never from a ZIP filename, a mailbox, or a
wall-clock import time. The export observation time is supplied by the caller
and is kept separate from conversation and message timestamps.
"""

from __future__ import annotations

from ..chatgpt_import.account import AccountError, resolve_account
from ..chatgpt_import.models import ParseResult
from .models import TIMESTAMP_REQUIRED, ExportIdentity


class ExportIdentityError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def build_export_identity(
    parsed: ParseResult,
    account_alias: str,
    export_observed_at: str,
) -> ExportIdentity:
    if not export_observed_at or not isinstance(export_observed_at, str):
        raise ExportIdentityError(TIMESTAMP_REQUIRED)
    try:
        account = resolve_account(account_alias)
    except AccountError as exc:
        raise ExportIdentityError(exc.code) from None
    if not parsed.source_export_id:
        raise ExportIdentityError("EXPORT_HASH_UNAVAILABLE")
    message_count = sum(len(conversation.messages) for conversation in parsed.conversations)
    return ExportIdentity(
        account_alias=account.alias,
        export_content_hash=parsed.source_export_id,
        export_format=parsed.export_format,
        export_observed_at=export_observed_at,
        conversation_count=len(parsed.conversations),
        message_count=message_count,
    )


def is_same_export(previous_hash: str | None, identity: ExportIdentity) -> bool:
    return isinstance(previous_hash, str) and previous_hash == identity.export_content_hash
