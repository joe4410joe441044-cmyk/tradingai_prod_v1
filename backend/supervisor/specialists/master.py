"""Master Supervisor: deterministic aggregation of all Specialist findings.

The Master is the single aggregation/explanation layer.  It collects typed
specialist results, preserves provenance/uncertainty, ranks severity
deterministically, and identifies explicit cross-domain contradictions from
evidence.  It executes no fixes, changes no runtime, and grants no authority.
"""

from __future__ import annotations

from datetime import datetime

from .contracts import (
    CrossDomainFinding,
    MasterSupervisorAssessment,
    SourceReference,
    SpecialistFinding,
    SpecialistSeverity,
    SpecialistStatus,
)
from .common import dedupe_reason_codes, dedupe_references, unique_warnings
from .severity import worst_severity, worst_status

_MM_BLOCK_FINDINGS = frozenset({
    "MM_ENTRY_BLOCKED", "MM_LOCKED", "MM_DEFENSIVE", "MM_CAUTION", "MM_RECOVERY_MODE",
})
_EXECUTION_EVIDENCE_PRESENT = frozenset({
    "EXECUTION_TRACE_COMPLETE", "ORDER_WITHOUT_CONFIRMED_FILL",
    "EXECUTION_ORDER_PENDING", "EXECUTION_REJECTED", "EXECUTION_FAILED",
})


def _codes(specialist: SpecialistFinding) -> set[str]:
    return {obs.code for obs in specialist.findings}


def _refs_of(specialists: list[SpecialistFinding]) -> tuple[SourceReference, ...]:
    refs: list[SourceReference] = []
    for item in specialists:
        refs.extend(item.sourceReferences)
    return dedupe_references(refs)


def _cross_domain(specialists: list[SpecialistFinding]) -> tuple[CrossDomainFinding, ...]:
    by_id = {item.specialistId: item for item in specialists}
    findings: list[CrossDomainFinding] = []

    strategy = by_id.get("STRATEGY")
    execution = by_id.get("EXECUTION")
    mm = by_id.get("MONEY_MANAGEMENT")
    health = by_id.get("SYSTEM_HEALTH")

    # Strategy intent present but execution shows no complete/confirmed evidence.
    if strategy is not None and execution is not None:
        strategy_codes = _codes(strategy)
        execution_codes = _codes(execution)
        if "STRATEGY_DECISION_PRESENT" in strategy_codes and not (
            execution_codes & set(_EXECUTION_EVIDENCE_PRESENT)
        ):
            participants = [strategy.specialistId, execution.specialistId]
            findings.append(CrossDomainFinding(
                code="STRATEGY_INTENT_WITHOUT_EXECUTION", severity=SpecialistSeverity.WARNING,
                detail="Strategy reports entry intent but execution evidence is absent or incomplete.",
                participants=tuple(participants), references=_refs_of([strategy, execution]),
            ))

    # A defensive/blocked MM state coexisting with an execution order/fill evidence.
    if mm is not None and execution is not None:
        mm_codes = _codes(mm)
        execution_codes = _codes(execution)
        if (mm_codes & _MM_BLOCK_FINDINGS) and (execution_codes & _EXECUTION_EVIDENCE_PRESENT):
            findings.append(CrossDomainFinding(
                code="MM_BLOCKED_BUT_EXECUTION_PRESENT", severity=SpecialistSeverity.CRITICAL,
                detail="Money Management defers/block entry yet execution order evidence exists.",
                participants=tuple([mm.specialistId, execution.specialistId]),
                references=_refs_of([mm, execution]),
            ))

    # Unreliable health evidence while strategy reports a current decision.
    if strategy is not None and health is not None:
        strategy_codes = _codes(strategy)
        health_status = health.status
        if (
            "STRATEGY_DECISION_PRESENT" in strategy_codes
            and health_status in {
                SpecialistStatus.UNKNOWN, SpecialistStatus.UNAVAILABLE, SpecialistStatus.WARNING,
            }
            and health.freshness.value not in {"FRESH"}
        ):
            findings.append(CrossDomainFinding(
                code="EVIDENCE_RELIABILITY_WARNING", severity=SpecialistSeverity.WARNING,
                detail="Strategy appears current but system-health evidence is unreliable.",
                participants=tuple([health.specialistId, strategy.specialistId]),
                references=_refs_of([health, strategy]),
            ))

    return tuple(sorted(findings, key=lambda item: (item.code, item.severity.value)))


def aggregate_specialists(
    specialists: tuple[SpecialistFinding, ...],
    now: datetime,
) -> MasterSupervisorAssessment:
    ordered = tuple(sorted(specialists, key=lambda item: item.specialistId))
    if not ordered:
        return MasterSupervisorAssessment(
            specialists=(), overallStatus=SpecialistStatus.UNKNOWN,
            highestSeverity=SpecialistSeverity.UNKNOWN, crossDomainFindings=(),
            reasonCodes=(), sourceReferences=(), generatedAt=now,
            warnings=("NO_SPECIALISTS",),
        )
    overall_status = worst_status(item.status for item in ordered)
    highest_severity = worst_severity(item.severity for item in ordered)
    cross = _cross_domain(list(ordered))

    reasons = dedupe_reason_codes(
        code for item in ordered for code in item.reasonCodes
    )
    all_refs = _refs_of(list(ordered))
    warnings = unique_warnings(w for item in ordered for w in item.warnings)

    return MasterSupervisorAssessment(
        specialists=ordered,
        overallStatus=overall_status,
        highestSeverity=highest_severity,
        crossDomainFindings=cross,
        reasonCodes=reasons,
        sourceReferences=all_refs,
        generatedAt=now,
        warnings=warnings,
    )
