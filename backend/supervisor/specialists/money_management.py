"""Money Management Specialist: deterministic interpretation of MM evidence.

This specialist reuses the existing read-only MM context (``build_mm_shadow_context``)
and the authoritative ``snapshot.moneyManagement`` observation.  Money Management
remains authoritative for its own domain; the specialist only interprets it and
never modifies MM configuration, budget, exposure, or authority.
"""

from __future__ import annotations

from datetime import datetime

from .contracts import (
    Freshness,
    SourceReference,
    SpecialistFinding,
    SpecialistObservation,
    SpecialistSeverity,
    SpecialistStatus,
)
from ..contracts import CapitalSource, ReadOnlySupervisorSnapshot
from ..mm_context_builder import build_mm_shadow_context
from .common import dedupe_reason_codes, dedupe_references, merge_observations, unique_warnings
from .severity import worst_status

SPECIALIST_ID = "MONEY_MANAGEMENT"
DOMAIN = "MONEY_MANAGEMENT"

_REQUIRED_FIELDS = (
    "capitalAuthority", "equity", "availableCapital", "riskBudget",
    "remainingExposure", "remainingPositionCapacity", "ruinGuardStatus",
)


def evaluate_money_management(
    snapshot: ReadOnlySupervisorSnapshot,
    now: datetime,
) -> SpecialistFinding:
    context = build_mm_shadow_context(snapshot)

    observations: list[SpecialistObservation] = []
    statuses: list[SpecialistStatus] = []
    reasons = list(context.reasonCodes)
    refs: list[SourceReference] = [
        SourceReference(
            sourceSubsystem="MONEY_MANAGEMENT_HTTP_BOUNDARY",
            sourceType="SUPERVISOR_SNAPSHOT:moneyManagement",
            sourceIdentifier=context.mmEvaluatedAt.isoformat() if context.mmEvaluatedAt else "moneyManagement",
            timestamp=context.mmEvaluatedAt.isoformat() if context.mmEvaluatedAt else None,
            linkageMethod="SUPERVISOR_SNAPSHOT",
        )
    ]
    warnings: list[str] = []

    present = sum(
        1
        for field in _REQUIRED_FIELDS
        if getattr(context, field, None) not in (None, "", "UNKNOWN")
    )
    confidence = present / len(_REQUIRED_FIELDS)

    missing_fields = [
        field for field in _REQUIRED_FIELDS
        if getattr(context, field, None) in (None, "", "UNKNOWN")
    ]
    if context.mmFreshness is Freshness.MISSING or (
        context.capitalAuthority is None and context.equity is None
    ):
        observations.append(SpecialistObservation(
            code="MM_INPUT_INCOMPLETE", severity=SpecialistSeverity.UNKNOWN,
            detail="Money Management authoritative input is missing or incomplete.",
        ))
        statuses.append(SpecialistStatus.UNAVAILABLE)
        warnings.append("MM_INPUT_INCOMPLETE")
    elif missing_fields:
        observations.append(SpecialistObservation(
            code="MM_INPUT_INCOMPLETE", severity=SpecialistSeverity.UNKNOWN,
            detail="Money Management input is incomplete: " + ", ".join(missing_fields) + ".",
        ))
        statuses.append(SpecialistStatus.UNKNOWN)
        warnings.append("MM_INPUT_INCOMPLETE")

    if context.mmFreshness is Freshness.STALE:
        observations.append(SpecialistObservation(
            code="MM_EVIDENCE_STALE", severity=SpecialistSeverity.WARNING,
            detail="Money Management authority evidence is stale.",
        ))
        statuses.append(SpecialistStatus.WARNING)
    elif context.mmFreshness in {Freshness.CONFLICTED, Freshness.UNKNOWN}:
        observations.append(SpecialistObservation(
            code="MM_EVIDENCE_UNRELIABLE", severity=SpecialistSeverity.UNKNOWN,
            detail=f"Money Management authority freshness is {context.mmFreshness.value}.",
        ))
        statuses.append(SpecialistStatus.UNKNOWN)

    if context.capitalSource is CapitalSource.UNKNOWN:
        observations.append(SpecialistObservation(
            code="MM_CAPITAL_SOURCE_UNKNOWN", severity=SpecialistSeverity.UNKNOWN,
            detail="Money Management capital source is unknown.",
        ))
        statuses.append(SpecialistStatus.UNKNOWN)

    ruin_guard = (context.ruinGuardStatus or "UNKNOWN").upper()
    if ruin_guard == "LOCKED":
        observations.append(SpecialistObservation(
            code="MM_LOCKED", severity=SpecialistSeverity.CRITICAL,
            detail="Money Management ruin guard is locked.",
        ))
        statuses.append(SpecialistStatus.CRITICAL)
    elif ruin_guard in {"DEFENSIVE"}:
        observations.append(SpecialistObservation(
            code="MM_DEFENSIVE", severity=SpecialistSeverity.WARNING,
            detail="Money Management is in defensive risk posture.",
        ))
        statuses.append(SpecialistStatus.WARNING)
    elif ruin_guard in {"CAUTION"}:
        observations.append(SpecialistObservation(
            code="MM_CAUTION", severity=SpecialistSeverity.WARNING,
            detail="Money Management is in caution risk posture.",
        ))
        statuses.append(SpecialistStatus.WARNING)
    elif ruin_guard in {"RECOVERY_25", "RECOVERY_50"}:
        observations.append(SpecialistObservation(
            code="MM_RECOVERY_MODE", severity=SpecialistSeverity.WARNING,
            detail="Money Management is in recovery posture.",
        ))
        statuses.append(SpecialistStatus.WARNING)
    elif ruin_guard in {"UNKNOWN", "UNAVAILABLE"}:
        observations.append(SpecialistObservation(
            code="MM_RISK_STATE_UNKNOWN", severity=SpecialistSeverity.UNKNOWN,
            detail="Money Management risk state is unknown.",
        ))
        statuses.append(SpecialistStatus.UNKNOWN)
    elif ruin_guard in {"NORMAL", "PASS"}:
        observations.append(SpecialistObservation(
            code="MM_NORMAL", severity=SpecialistSeverity.INFO,
            detail="Money Management risk posture is normal.",
        ))

    if context.authorityFresh is False:
        observations.append(SpecialistObservation(
            code="MM_AUTHORITY_STALE", severity=SpecialistSeverity.WARNING,
            detail="Money Management authority is not fresh.",
        ))
        statuses.append(SpecialistStatus.WARNING)

    if context.executionEntryAllowed is False:
        observations.append(SpecialistObservation(
            code="MM_ENTRY_BLOCKED", severity=SpecialistSeverity.WARNING,
            detail="Money Management entry gate is blocking new entries.",
        ))
        statuses.append(SpecialistStatus.WARNING)
    elif context.executionEntryAllowed is True and ruin_guard in {"NORMAL", "PASS"}:
        observations.append(SpecialistObservation(
            code="MM_ENTRY_ALLOWED", severity=SpecialistSeverity.INFO,
            detail="Money Management entry gate allows new entries.",
        ))

    if context.mmRegime is not None and str(context.mmRegime).upper() in {"UNKNOWN", "UNAVAILABLE"}:
        observations.append(SpecialistObservation(
            code="MM_REGIME_UNKNOWN", severity=SpecialistSeverity.UNKNOWN,
            detail="Money Management regime is unknown.",
        ))
        statuses.append(SpecialistStatus.UNKNOWN)

    if not statuses:
        status = SpecialistStatus.HEALTHY
    else:
        status = worst_status(statuses)

    sev_values = [obs.severity for obs in observations]
    if any(sev is SpecialistSeverity.CRITICAL for sev in sev_values):
        severity = SpecialistSeverity.CRITICAL
    elif any(sev is SpecialistSeverity.UNKNOWN for sev in sev_values):
        severity = SpecialistSeverity.UNKNOWN
    elif any(sev is SpecialistSeverity.WARNING for sev in sev_values):
        severity = SpecialistSeverity.WARNING
    else:
        severity = SpecialistSeverity.INFO

    summary = f"Money Management evaluated as {status.value}."
    return SpecialistFinding(
        specialistId=SPECIALIST_ID,
        domain=DOMAIN,
        status=status,
        severity=severity,
        summary=summary,
        findings=merge_observations(observations),
        reasonCodes=dedupe_reason_codes(reasons),
        sourceReferences=dedupe_references(refs),
        evidenceTimestamp=context.mmEvaluatedAt or snapshot.capturedAt,
        freshness=context.mmFreshness,
        confidence=round(confidence, 4),
        warnings=unique_warnings(warnings),
        generatedAt=now,
    )
