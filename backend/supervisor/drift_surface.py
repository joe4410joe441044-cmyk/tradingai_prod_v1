"""Bounded, read-only drift notice for the Supervisor (D-7).

READ_ONLY_ANALYSIS.  INFORMATION ONLY.

D-7 lets a Supervisor surface drift/provenance warnings (source stale, source
unavailable, canonical mismatch, evidence conflict, provenance unknown).  This
module projects a deterministic
``backend.knowledge_core.drift.DriftAssessment`` into a small, typed,
non-secret ``SupervisorDriftNotice``.  It can never repair anything: there is no
resync / reload / rewrite / repair / apply / approve surface, and the authority
fields are all locked to ``NONE`` / ``READ_ONLY_ANALYSIS``.

It is provider-neutral and never depends on an LLM to determine drift state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import Field, field_validator

from backend.supervisor.contracts import SupervisorContract

from backend.knowledge_core.drift import (
    D7_REASON_CODES,
    DriftAssessment,
    DriftStatus,
)

MAX_NOTICE_TEXT = 220
MAX_NOTICE_SOURCE_REFERENCES = 12
MAX_NOTICE_REASON_CODES = 16
MAX_NOTICE_WARNINGS = 12

_ALLOWED_STATUSES = frozenset(item.value for item in DriftStatus)
_ALLOWED_REASON_CODES = frozenset(D7_REASON_CODES)


def _clip_text(value: Optional[str], limit: int = MAX_NOTICE_TEXT) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:limit]


class SupervisorDriftNotice(SupervisorContract):
    """A bounded, typed warning about one provenance/drift assessment.

    The notice exists to be surfaced.  It carries no fix, no approval and no
    operational capability.
    """

    schemaVersion: int = Field(default=1, ge=1, le=1)
    noticeId: Annotated[str, Field(min_length=1, max_length=128)]
    status: Annotated[str, Field(min_length=1, max_length=24)]
    sourceKind: Annotated[str, Field(min_length=1, max_length=32)]
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=MAX_NOTICE_REASON_CODES)
    sourceReferences: tuple[str, ...] = Field(
        default=(), max_length=MAX_NOTICE_SOURCE_REFERENCES
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=MAX_NOTICE_WARNINGS)
    generatedAt: datetime
    authority: Literal["READ_ONLY_ANALYSIS"] = "READ_ONLY_ANALYSIS"
    operationalAuthority: Literal["NONE"] = "NONE"
    mutationAuthority: Literal["NONE"] = "NONE"

    @field_validator("status")
    @classmethod
    def status_allowlisted(cls, value: str) -> str:
        if value not in _ALLOWED_STATUSES:
            raise ValueError("status is not an allowlisted drift status")
        return value

    @field_validator("generatedAt")
    @classmethod
    def aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generatedAt must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("reasonCodes", "warnings")
    @classmethod
    def bounded_tokens(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > MAX_NOTICE_TEXT for value in values):
            raise ValueError("notice token must be non-blank and bounded")
        return values

    @property
    def has_repair_authority(self) -> bool:
        return False


def build_supervisor_drift_notice(
    assessment: DriftAssessment,
    *,
    generated_at: Optional[datetime] = None,
) -> SupervisorDriftNotice:
    """Project a DriftAssessment into a bounded, read-only Supervisor notice.

    The projection is allowlisted and non-secret; it never carries a raw
    snapshot, provider output, credential, or runtime dump, and it never
    mutates the provided assessment.
    """
    if not isinstance(assessment, DriftAssessment):
        raise TypeError("typed DriftAssessment required")

    refs: list[str] = []
    for finding in assessment.findings:
        for reference in (finding.actual_reference, finding.expected_reference):
            if reference:
                text = _clip_text(reference)
                if text and text not in refs:
                    refs.append(text)
    if not refs:
        refs.append(_clip_text(assessment.subject) or "UNKNOWN")
    refs = tuple(refs[:MAX_NOTICE_SOURCE_REFERENCES])

    reason_codes = tuple(
        code for code in assessment.reason_codes
        if code in _ALLOWED_REASON_CODES
    )[:MAX_NOTICE_REASON_CODES]

    warnings: list[str] = []
    for finding in assessment.findings:
        for warning in finding.warnings:
            text = _clip_text(warning)
            if text and text not in warnings:
                warnings.append(text)
    warnings = tuple(warnings[:MAX_NOTICE_WARNINGS])

    if generated_at is not None:
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        now = generated_at.astimezone(timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    return SupervisorDriftNotice(
        noticeId=_clip_text(assessment.subject, 128) or "UNKNOWN",
        status=assessment.status.value,
        sourceKind=assessment.source_kind.value,
        reasonCodes=reason_codes,
        sourceReferences=refs,
        warnings=warnings,
        generatedAt=now,
    )
