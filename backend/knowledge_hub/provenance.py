"""Shared provenance envelope.

``RUNTIME_VERIFIED`` and ``EXCHANGE_VERIFIED`` are never assigned here.
Collection success and factual authority stay separate fields.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import SCHEMA_VERSION
from .models import Provenance


FORBIDDEN_TRUTH = frozenset({"RUNTIME_VERIFIED", "EXCHANGE_VERIFIED"})
AUTHORITY_SCOPE = "NONE"


def stamp(clock) -> str:
    moment = clock() if clock is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("TIMESTAMP_REQUIRED")
    return moment.astimezone(timezone.utc).isoformat()


def build_provenance(
    *,
    source_type: str,
    source_identifier: str,
    collected_at: str,
    truth_kind: str,
    record_type: str,
    verification_state: str,
    content_hash: str | None = None,
    relative_path: str | None = None,
    commit_sha: str | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    reported_at: str | None = None,
    observed_at: str | None = None,
    source_timestamp: str | None = None,
    superseded_by: str | None = None,
) -> Provenance:
    if truth_kind in FORBIDDEN_TRUTH or verification_state in FORBIDDEN_TRUTH:
        raise ValueError("UNPROVEN_AUTHORITY")
    return Provenance(
        schema_version=SCHEMA_VERSION,
        source_type=source_type,
        source_identifier=source_identifier,
        collected_at=collected_at,
        content_hash=content_hash,
        verification_state=verification_state,
        authority_scope=AUTHORITY_SCOPE,
        record_type=record_type,
        truth_kind=truth_kind,
        relative_path=relative_path,
        commit_sha=commit_sha,
        branch=branch,
        worktree=worktree,
        reported_at=reported_at,
        observed_at=observed_at,
        source_timestamp=source_timestamp,
        superseded_by=superseded_by,
    )
