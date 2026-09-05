"""Deterministic severity/status aggregation helpers.

Aggregation is a pure ordering function over typed enums.  It never consults an
LLM and never picks a severity based on ambiguous evidence: uncertain evidence
ranks as ``UNKNOWN`` and unavailable evidence ranks as ``UNAVAILABLE`` so that
missing data never collapses toward healthy.
"""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import (
    FINDING_SEVERITY_RANK,
    STATUS_SEVERITY_RANK,
    SpecialistSeverity,
    SpecialistStatus,
)


def worst_status(statuses: Iterable[SpecialistStatus]) -> SpecialistStatus:
    """Return the most severe status under the fail-closed ladder."""
    values = list(statuses)
    if not values:
        return SpecialistStatus.UNKNOWN
    return max(values, key=lambda item: STATUS_SEVERITY_RANK[item])


def worst_severity(severities: Iterable[SpecialistSeverity]) -> SpecialistSeverity:
    """Return the most severe finding severity under the fail-closed ladder."""
    values = list(severities)
    if not values:
        return SpecialistSeverity.INFO
    return max(values, key=lambda item: FINDING_SEVERITY_RANK[item])


def status_from_finding_severity(severity: SpecialistSeverity) -> SpecialistStatus:
    """Map a finding-severity to the closest overall status (not healthy-safe)."""
    return {
        SpecialistSeverity.INFO: SpecialistStatus.HEALTHY,
        SpecialistSeverity.WARNING: SpecialistStatus.WARNING,
        SpecialistSeverity.CRITICAL: SpecialistStatus.CRITICAL,
        SpecialistSeverity.UNKNOWN: SpecialistStatus.UNKNOWN,
    }[severity]
