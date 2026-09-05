"""Bounded, typed drift/provenance context for the AI Advisor (D-7).

INFORMATION_ONLY.  READ_ONLY.

This is a small, allowlisted projection of deterministic
``backend.knowledge_core.drift.DriftAssessment`` objects so the Advisor can
distinguish CURRENT information from STALE / DRIFTED / CONFLICTING / UNKNOWN /
UNAVAILABLE evidence without ever being shown raw provenance or runtimes.  It
deliberately:

* never floods the LLM: every collection is hard-bounded and truncation is an
  explicit fact;
* never represents a DRIFTED / CONFLICTING / STALE / UNKNOWN / UNAVAILABLE item
  as CURRENT;
* keeps the existing prompt separations intact (this is metadata that augments a
  block; it does not merge canonical knowledge, runtime context, conversation
  history, historical trace evidence or the current request);
* never reads external state, never mutates an input assessment, and is
  provider-neutral.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.knowledge_core.drift import D7_REASON_CODES, DriftAssessment, DriftStatus

MAX_DRIFT_ITEMS = 8
MAX_DRIFT_REASON_CODES_PER_ITEM = 8
MAX_DRIFT_WARNINGS_PER_ITEM = 8
MAX_DRIFT_TEXT = 220
MAX_DRIFT_SOURCE_REFERENCE = 128

ALLOWED_DRIFT_STATUSES = frozenset(item.value for item in DriftStatus)
ALLOWED_DRIFT_REASON_CODES = frozenset(D7_REASON_CODES)

_STATUS_NOT_CURRENT = frozenset({
    DriftStatus.STALE.value,
    DriftStatus.DRIFTED.value,
    DriftStatus.CONFLICTING.value,
    DriftStatus.UNKNOWN.value,
    DriftStatus.UNAVAILABLE.value,
})


def _clip_text(value: Optional[str], limit: int = MAX_DRIFT_TEXT) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:limit]


def _bound_reference(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_DRIFT_SOURCE_REFERENCE]


class AdvisorDriftItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    itemId: Annotated[str, Field(min_length=1, max_length=MAX_DRIFT_SOURCE_REFERENCE)]
    status: Annotated[str, Field(min_length=1, max_length=24)]
    sourceKind: Annotated[str, Field(min_length=1, max_length=32)]
    asCurrent: bool = False
    reasonCodes: Tuple[Annotated[str, Field(min_length=1, max_length=80)], ...] = Field(
        default_factory=tuple
    )
    sourceReference: Optional[Annotated[str, Field(max_length=MAX_DRIFT_SOURCE_REFERENCE)]] = None
    warnings: Tuple[Annotated[str, Field(min_length=1, max_length=MAX_DRIFT_TEXT)], ...] = Field(
        default_factory=tuple
    )
    assessedAt: Optional[datetime] = None
    truncated: bool = False

    @field_validator("status")
    @classmethod
    def status_allowlisted(cls, value: str) -> str:
        if value not in ALLOWED_DRIFT_STATUSES:
            raise ValueError("status is not an allowlisted drift status")
        return value

    @field_validator("assessedAt")
    @classmethod
    def aware_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assessedAt must be timezone-aware")
        return value.astimezone(timezone.utc)


class AdvisorDriftContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schemaVersion: str = "advisor-drift/v1"
    items: Tuple[AdvisorDriftItem, ...] = Field(default_factory=tuple)
    truncated: bool = False
    omittedCount: int = 0
    warning: Optional[Annotated[str, Field(min_length=1, max_length=MAX_DRIFT_TEXT)]] = None

    @property
    def is_empty(self) -> bool:
        return not self.items


def _project(
    assessment: DriftAssessment,
    *,
    max_reason_codes: int,
    max_warnings: int,
) -> AdvisorDriftItem:
    if not isinstance(assessment, DriftAssessment):
        raise TypeError("typed DriftAssessment required")
    raw_codes = [c for c in assessment.reason_codes if c in ALLOWED_DRIFT_REASON_CODES]
    codes = tuple(raw_codes[:max_reason_codes])
    codes_truncated = len(raw_codes) > max_reason_codes

    raw_warnings: list[str] = []
    for finding in assessment.findings:
        for warning in finding.warnings:
            clipped = _clip_text(warning)
            if clipped and clipped not in raw_warnings:
                raw_warnings.append(clipped)
    warnings = tuple(raw_warnings[:max_warnings])
    warnings_truncated = len(raw_warnings) > max_warnings

    best_reference = None
    for finding in assessment.findings:
        reference = _bound_reference(finding.actual_reference)
        if reference:
            best_reference = reference
            break
        reference = _bound_reference(finding.expected_reference)
        if reference:
            best_reference = reference
            break
    if best_reference is None:
        best_reference = _bound_reference(assessment.subject)
    if best_reference is None:
        best_reference = "UNKNOWN"

    status = assessment.status.value
    return AdvisorDriftItem(
        itemId=_clip_text(assessment.subject, MAX_DRIFT_SOURCE_REFERENCE) or "UNKNOWN",
        status=status,
        sourceKind=assessment.source_kind.value,
        asCurrent=(status == DriftStatus.CURRENT.value),
        reasonCodes=codes,
        sourceReference=best_reference,
        warnings=warnings,
        assessedAt=assessment.assessed_at,
        truncated=codes_truncated or warnings_truncated,
    )


def build_advisor_drift_context(
    assessments: Sequence[DriftAssessment],
    *,
    max_items: int = MAX_DRIFT_ITEMS,
    max_reason_codes: int = MAX_DRIFT_REASON_CODES_PER_ITEM,
    max_warnings: int = MAX_DRIFT_WARNINGS_PER_ITEM,
) -> AdvisorDriftContext:
    """Build a bounded, allowlisted drift context from DriftAssessments.

    Truncation (of items, reason codes or warnings) is surfaced explicitly rather
    than silently dropped.  The projection never mutates its inputs and never
    exposes secrets or raw runtimes.
    """
    if max_items < 0:
        raise ValueError("max_items must be non-negative")
    if max_reason_codes < 0:
        raise ValueError("max_reason_codes must be non-negative")
    if max_warnings < 0:
        raise ValueError("max_warnings must be non-negative")

    ordered = list(assessments)
    omitted = max(0, len(ordered) - max_items)
    selected = ordered[: max_items if max_items else 0]
    items = tuple(
        _project(item, max_reason_codes=max_reason_codes, max_warnings=max_warnings)
        for item in selected
        if isinstance(item, DriftAssessment)
    )
    truncated = bool(omitted) or any(item.truncated for item in items)
    warning = None
    if truncated:
        reasons = []
        if omitted:
            reasons.append(f"omitted {omitted} drift assessments")
        if any(item.truncated for item in items):
            reasons.append("some items truncated")
        warning = "; ".join(reasons)
    return AdvisorDriftContext(
        items=items,
        truncated=truncated,
        omittedCount=omitted,
        warning=warning,
    )


def drift_context_lines(context: AdvisorDriftContext) -> list[tuple[str, object]]:
    """Return allowlisted (name, value) pairs for the prompt layer."""
    if context is None:
        return [("classification", "DRIFT / PROVENANCE")]
    lines: list[tuple[str, object]] = [
        ("classification", "DRIFT / PROVENANCE"),
        ("itemCount", len(context.items)),
    ]
    if context.truncated:
        lines.append(("truncated", True))
        lines.append(("omittedCount", context.omittedCount))
        if context.warning:
            lines.append(("warning", context.warning))
    if not context.items:
        lines.append(("status", "NOT_AVAILABLE"))
    for index, item in enumerate(context.items):
        prefix = f"item[{index}]"
        lines.append((f"{prefix}.itemId", item.itemId))
        lines.append((f"{prefix}.status", item.status))
        lines.append((f"{prefix}.sourceKind", item.sourceKind))
        if item.asCurrent:
            lines.append((f"{prefix}.asCurrent", True))
        if item.sourceReference:
            lines.append((f"{prefix}.sourceReference", item.sourceReference))
        if item.reasonCodes:
            lines.append((f"{prefix}.reasonCodes", ",".join(item.reasonCodes)))
        if item.warnings:
            lines.append((f"{prefix}.warnings", ",".join(item.warnings)))
        if item.truncated:
            lines.append((f"{prefix}.truncated", True))
    return lines


def render_drift_context(context: AdvisorDriftContext) -> str:
    """Render the bounded drift context as plain `name=value` content lines."""
    return "\n".join(
        f"{name}={_render_scalar(value)}" for name, value in drift_context_lines(context)
    )


def _render_scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)
