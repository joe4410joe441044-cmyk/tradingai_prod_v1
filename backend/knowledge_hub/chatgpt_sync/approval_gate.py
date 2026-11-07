"""Per-account, per-export, per-database approval gate.

An approval is bound to one account alias, one export content hash, and one
explicit database path. It is never inferred from a previous approval, a
filename, or another account. A missing preview or any mismatch blocks import
before a write begins.
"""

from __future__ import annotations

from pathlib import Path

from .models import APPROVAL_MISMATCH, Approval, SyncPreview


class ApprovalError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def create_approval(
    preview: SyncPreview,
    *,
    store_path: str | Path,
    approved_at: str,
    approved_by: str = "OPERATOR",
) -> Approval:
    if preview.export_identity is None:
        raise ApprovalError("PREVIEW_REQUIRED")
    if not approved_at or not isinstance(approved_at, str):
        raise ApprovalError("TIMESTAMP_REQUIRED")
    return Approval(
        account_alias=preview.account_alias,
        export_content_hash=preview.export_identity.export_content_hash,
        store_path=str(store_path),
        approved_at=approved_at,
        approved_by=approved_by,
    )


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except (OSError, RuntimeError):
        return False


def validate_approval(
    approval: Approval | None,
    *,
    preview: SyncPreview | None,
    account_alias: str,
    export_content_hash: str,
    store_path: str | Path,
) -> None:
    if preview is None or preview.status != "OK" or preview.export_identity is None:
        raise ApprovalError("PREVIEW_REQUIRED")
    if approval is None:
        raise ApprovalError("APPROVAL_REQUIRED")
    if approval.account_alias != account_alias:
        raise ApprovalError(APPROVAL_MISMATCH)
    if approval.export_content_hash != export_content_hash:
        raise ApprovalError(APPROVAL_MISMATCH)
    if not _same_path(approval.store_path, store_path):
        raise ApprovalError(APPROVAL_MISMATCH)
    if (
        preview.account_alias != account_alias
        or preview.export_identity.export_content_hash != export_content_hash
    ):
        raise ApprovalError(APPROVAL_MISMATCH)
