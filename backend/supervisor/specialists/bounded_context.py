"""Bounded, sanitized context for optional Supervisor LLM interpretation.

The context is a typed, allow-listed projection of the deterministic assessment.
It copies only non-secret observation fields, applies explicit hard bounds, and
marks any truncation so evidence is never silently omitted.  The LLM is never
the source of specialist truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, field_validator

from .contracts import (
    MasterSupervisorAssessment,
    SourceReference,
    SpecialistFinding,
    SpecialistSeverity,
)
from ..contracts import SupervisorContract


@dataclass(frozen=True)
class BoundedContextLimits:
    """Hard limits on the LLM-facing context.  No default is authoritative."""

    maxSpecialists: int = 8
    maxFindingsPerSpecialist: int = 8
    maxReasonCodes: int = 40
    maxSourceReferences: int = 40
    maxCrossDomain: int = 12
    maxTextLength: int = 220
    maxWarnings: int = 20

    def __post_init__(self) -> None:
        for name in (
            "maxSpecialists", "maxFindingsPerSpecialist", "maxReasonCodes",
            "maxSourceReferences", "maxCrossDomain", "maxTextLength", "maxWarnings",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


class BoundedFinding(SupervisorContract):
    code: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    detail: str = Field(min_length=1, max_length=500)
    truncated: bool = False


class BoundedSpecialist(SupervisorContract):
    specialistId: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=20)
    severity: str = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=500)
    findings: tuple[BoundedFinding, ...] = Field(default=(), max_length=20)
    findingCount: int = Field(ge=0)
    findingTruncated: bool = False
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=80)
    warnings: tuple[str, ...] = Field(default=(), max_length=20)


class BoundedCrossDomain(SupervisorContract):
    code: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    detail: str = Field(min_length=1, max_length=500)
    participants: tuple[str, ...] = Field(default=(), max_length=10)
    truncated: bool = False


class BoundedSourceReference(SupervisorContract):
    sourceSubsystem: str = Field(min_length=1, max_length=100)
    sourceType: str = Field(min_length=1, max_length=120)
    sourceIdentifier: str = Field(max_length=120)


class BoundedLlmContext(SupervisorContract):
    schemaVersion: int = Field(default=1, ge=1, le=1)
    overallStatus: str = Field(min_length=1, max_length=20)
    highestSeverity: str = Field(min_length=1, max_length=20)
    specialists: tuple[BoundedSpecialist, ...] = Field(default=(), max_length=12)
    crossDomainFindings: tuple[BoundedCrossDomain, ...] = Field(default=(), max_length=12)
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=80)
    sourceReferences: tuple[BoundedSourceReference, ...] = Field(default=(), max_length=80)
    warnings: tuple[str, ...] = Field(default=(), max_length=20)
    truncated: bool = False
    generatedAt: datetime

    @field_validator("generatedAt")
    @classmethod
    def aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


def _clip_text(value: str, limit: int) -> tuple[str, bool]:
    if value is None:
        return "", False
    if len(value) <= limit:
        return value, False
    return value[: limit - 1] + "…", True


def _bound_finding(code: str, severity: SpecialistSeverity, detail: str, limits: BoundedContextLimits) -> BoundedFinding:
    clipped, truncated = _clip_text(detail, limits.maxTextLength)
    return BoundedFinding(code=code, severity=severity.value, detail=clipped, truncated=truncated)


def _bound_specialist(source: SpecialistFinding, limits: BoundedContextLimits) -> BoundedSpecialist:
    findings = list(source.findings[: limits.maxFindingsPerSpecialist])
    bound_findings = tuple(
        _bound_finding(item.code, item.severity, item.detail, limits) for item in findings
    )
    finding_truncated = len(source.findings) > limits.maxFindingsPerSpecialist
    return BoundedSpecialist(
        specialistId=source.specialistId,
        domain=source.domain,
        status=source.status.value,
        severity=source.severity.value,
        summary=source.summary,
        findings=bound_findings,
        findingCount=len(source.findings),
        findingTruncated=finding_truncated,
        reasonCodes=tuple(source.reasonCodes[: limits.maxReasonCodes]),
        warnings=tuple(source.warnings[: limits.maxWarnings]),
    )


def _bound_reference(ref: SourceReference) -> BoundedSourceReference:
    return BoundedSourceReference(
        sourceSubsystem=ref.sourceSubsystem,
        sourceType=ref.sourceType,
        sourceIdentifier=ref.sourceIdentifier,
    )


def build_bounded_llm_context(
    assessment: MasterSupervisorAssessment,
    *,
    limits: BoundedContextLimits | None = None,
) -> BoundedLlmContext:
    """Project a deterministic assessment into a bounded LLM context.

    The projection allows only non-secret, typed observation fields; it never
    carries a raw snapshot, provider output, credential, or runtime dump.
    """
    effective = limits or BoundedContextLimits()

    specialists = tuple(
        _bound_specialist(item, effective)
        for item in assessment.specialists[: effective.maxSpecialists]
    )
    specialist_truncated = len(assessment.specialists) > effective.maxSpecialists

    cross = tuple(
        BoundedCrossDomain(
            code=item.code,
            severity=item.severity.value,
            detail=_clip_text(item.detail, effective.maxTextLength)[0],
            participants=item.participants,
            truncated=_clip_text(item.detail, effective.maxTextLength)[1],
        )
        for item in assessment.crossDomainFindings[: effective.maxCrossDomain]
    )
    cross_truncated = len(assessment.crossDomainFindings) > effective.maxCrossDomain

    references = tuple(
        _bound_reference(item) for item in assessment.sourceReferences[: effective.maxSourceReferences]
    )
    reference_truncated = len(assessment.sourceReferences) > effective.maxSourceReferences

    truncated = bool(
        specialist_truncated or cross_truncated or reference_truncated
        or len(assessment.reasonCodes) > effective.maxReasonCodes
        or len(assessment.warnings) > effective.maxWarnings
    )

    return BoundedLlmContext(
        overallStatus=assessment.overallStatus.value,
        highestSeverity=assessment.highestSeverity.value,
        specialists=specialists,
        crossDomainFindings=cross,
        reasonCodes=tuple(assessment.reasonCodes[: effective.maxReasonCodes]),
        sourceReferences=references,
        warnings=tuple(assessment.warnings[: effective.maxWarnings]),
        truncated=truncated,
        generatedAt=assessment.generatedAt,
    )
