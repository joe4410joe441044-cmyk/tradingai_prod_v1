"""Typed, provider-neutral deterministic contracts for D-6 Supervisor Specialists.

This module establishes the shared Specialist Finding contract and the
deterministic Master Supervisor assessment that aggregates specialist output.
It is observation-only: every produced value carries an explicit
``READ_ONLY_ANALYSIS`` authority and never exposes mutation or operational
capability.

These contracts are intentionally small and additive.  They reuse the existing
``SupervisorContract`` base (frozen, extra-field forbidden, stable serialization)
and the existing ``Freshness`` status enum; they do not duplicate the existing
``SupervisorState``/``SupervisorMode`` postures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from ..contracts import Freshness, SupervisorContract


class SpecialistStatus(str, Enum):
    """Deterministic specialist health status.

    Missing or unobservable evidence must never collapse to ``HEALTHY``; the
    status ladder is fail-closed: ``CRITICAL`` > ``UNAVAILABLE`` > ``UNKNOWN`` >
    ``WARNING`` > ``HEALTHY``.
    """

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class SpecialistSeverity(str, Enum):
    """Deterministic per-finding severity.

    ``UNKNOWN`` ranks above ``WARNING`` so that uncertain evidence is never
    silently downgraded toward healthy, but ``CRITICAL`` always surfaces first.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


# Fail-closed ordering: a confirmed CRITICAL is always most actionable; an
# UNAVAILABLE domain (no evidence at all) outranks UNKNOWN; UNKNOWN outranks a
# WARNING so uncertainty is not confused with a mild-but-observed defect.
STATUS_SEVERITY_RANK: dict[SpecialistStatus, int] = {
    SpecialistStatus.HEALTHY: 0,
    SpecialistStatus.WARNING: 1,
    SpecialistStatus.UNKNOWN: 2,
    SpecialistStatus.UNAVAILABLE: 3,
    SpecialistStatus.CRITICAL: 4,
}

FINDING_SEVERITY_RANK: dict[SpecialistSeverity, int] = {
    SpecialistSeverity.INFO: 0,
    SpecialistSeverity.WARNING: 1,
    SpecialistSeverity.UNKNOWN: 2,
    SpecialistSeverity.CRITICAL: 3,
}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class SourceReference(SupervisorContract):
    """Minimal provenance reference reused from D-5 evidence semantics.

    The field vocabulary mirrors ``backend.runtime.unified_trace.Provenance`` so
    that D-5 source references can be copied without a parallel contract.
    """

    sourceSubsystem: str = Field(min_length=1, max_length=100)
    sourceType: str = Field(min_length=1, max_length=120)
    sourceIdentifier: str = Field(max_length=120)
    timestamp: str | None = Field(default=None, max_length=64)
    linkageMethod: str = Field(default="EVIDENCE_REFERENCE", max_length=64)
    confidence: str | None = Field(default=None, max_length=64)

    @field_validator("sourceSubsystem", "sourceType", "linkageMethod")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provenance field must not be blank")
        return value


def reference_from_provenance(value: object) -> SourceReference:
    """Build a typed ``SourceReference`` from a D-5 provenance-like value.

    Accepts a ``backend.runtime.unified_trace.Provenance`` dataclass or any
    mapping exposing the same field vocabulary.  Never mutates the source.
    """
    get = getattr
    if hasattr(value, "to_dict"):
        source = value.to_dict()
    elif isinstance(value, dict):
        source = dict(value)
    else:
        source = value
    subsystem = get(source, "source_subsystem", None) or source.get("sourceSubsystem")
    if subsystem is not None and hasattr(subsystem, "value"):
        subsystem = subsystem.value
    source_type = get(source, "source_type", None) or source.get("sourceType")
    identifier = get(source, "source_identifier", None) or source.get("sourceIdentifier")
    timestamp = get(source, "timestamp", None) or source.get("timestamp")
    linkage = get(source, "linkage_method", None) or source.get("linkageMethod")
    confidence = get(source, "confidence", None) or source.get("confidence")
    return SourceReference(
        sourceSubsystem=str(subsystem or "UNKNOWN"),
        sourceType=str(source_type or "EVIDENCE"),
        sourceIdentifier=str(identifier or ""),
        timestamp=str(timestamp) if timestamp is not None else None,
        linkageMethod=str(linkage or "EVIDENCE_REFERENCE"),
        confidence=str(confidence) if confidence is not None else None,
    )


class SpecialistObservation(SupervisorContract):
    """A single deterministic finding produced from authoritative evidence."""

    code: str = Field(min_length=1, max_length=100)
    severity: SpecialistSeverity
    detail: str = Field(min_length=1, max_length=500)
    references: tuple[SourceReference, ...] = Field(default=(), max_length=20)

    @field_validator("code")
    @classmethod
    def code_uppercase(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("observation code must not be blank")
        return value.strip().upper()


class SpecialistFinding(SupervisorContract):
    """Bounded, deterministic output of a single Specialist."""

    specialistId: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=100)
    status: SpecialistStatus
    severity: SpecialistSeverity
    summary: str = Field(min_length=1, max_length=500)
    findings: tuple[SpecialistObservation, ...] = Field(default=(), max_length=40)
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=80)
    sourceReferences: tuple[SourceReference, ...] = Field(default=(), max_length=80)
    evidenceTimestamp: datetime | None = None
    freshness: Freshness = Freshness.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: tuple[str, ...] = Field(default=(), max_length=40)
    generatedAt: datetime
    authority: Literal["READ_ONLY_ANALYSIS"] = "READ_ONLY_ANALYSIS"
    operationalAuthority: Literal["NONE"] = "NONE"
    mutationAuthority: Literal["NONE"] = "NONE"

    @field_validator("evidenceTimestamp", "generatedAt")
    @classmethod
    def aware_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @field_validator("reasonCodes")
    @classmethod
    def bounded_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("reason code must be non-blank and bounded")
        return values

    @field_validator("warnings")
    @classmethod
    def bounded_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("warning must be non-blank and bounded")
        return values


class CrossDomainFinding(SupervisorContract):
    """A deterministic contradiction established across two or more specialists."""

    code: str = Field(min_length=1, max_length=100)
    severity: SpecialistSeverity
    detail: str = Field(min_length=1, max_length=500)
    participants: tuple[str, ...] = Field(min_length=2, max_length=10)
    references: tuple[SourceReference, ...] = Field(default=(), max_length=40)

    @field_validator("code")
    @classmethod
    def code_uppercase(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("cross-domain code must not be blank")
        return value.strip().upper()

    @field_validator("participants")
    @classmethod
    def participants_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("participant must be non-blank and bounded")
        return tuple(sorted(set(values)))


class MasterSupervisorAssessment(SupervisorContract):
    """Deterministic aggregation of all Specialist findings.

    This is the single aggregation/explanation layer.  It preserves provenance,
    reason codes, uncertainty, and per-specialist separation; it performs no
    runtime mutation.
    """

    schemaVersion: int = Field(default=1, ge=1, le=1)
    specialists: tuple[SpecialistFinding, ...] = Field(max_length=20)
    overallStatus: SpecialistStatus
    highestSeverity: SpecialistSeverity
    crossDomainFindings: tuple[CrossDomainFinding, ...] = Field(default=(), max_length=40)
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=200)
    sourceReferences: tuple[SourceReference, ...] = Field(default=(), max_length=200)
    generatedAt: datetime
    warnings: tuple[str, ...] = Field(default=(), max_length=40)
    authority: Literal["READ_ONLY_ANALYSIS"] = "READ_ONLY_ANALYSIS"
    operationalAuthority: Literal["NONE"] = "NONE"
    mutationAuthority: Literal["NONE"] = "NONE"

    @field_validator("generatedAt")
    @classmethod
    def aware_generated_at(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator("warnings")
    @classmethod
    def bounded_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("warning must be non-blank and bounded")
        return values


def utc_now() -> datetime:
    """Deterministic timestamp helper used by Specialist evaluators."""
    return datetime.now(timezone.utc)
