"""Strategy Specialist: deterministic interpretation of strategy decision evidence.

The specialist reads the authoritative read-only decision evidence and the D-5
INFORMATION_ONLY decision/no-trade/rejection linkage.  It never changes a
threshold, signal rule, parameter, or performs learning.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .contracts import (
    Freshness,
    SourceReference,
    SpecialistFinding,
    SpecialistObservation,
    SpecialistSeverity,
    SpecialistStatus,
)
from ..contracts import ReadOnlySupervisorSnapshot
from .common import (
    dedupe_reason_codes,
    dedupe_references,
    merge_observations,
    unique_warnings,
)

SPECIALIST_ID = "STRATEGY"
DOMAIN = "TRADING_DECISION"

_BUY_SELL = frozenset({"BUY", "SELL", "LONG", "SHORT", "ENTRY", "READY"})
_HOLD = frozenset({"HOLD", "NEUTRAL", "NONE"})
_ENTRY_BLOCK = frozenset({"BLOCK", "BLOCKED", "REJECTED", "DENIED", "FORBIDDEN"})
_SUPPRESSED = frozenset({"SUPPRESSED", "SUPPRESSION"})


def _node_status(node: object) -> str:
    return (getattr(node, "status", "") or "").upper()


def _reason_codes(traces: Iterable[object]) -> tuple[str, ...]:
    codes: list[str] = []
    for trace in traces:
        for code in getattr(trace, "reason_codes", ()) or ():
            value = getattr(code, "code", None) or getattr(code, "reason_code", None)
            if value:
                codes.append(str(value))
    return dedupe_reason_codes(codes)


def _subsystem(provenance: object) -> str:
    value = getattr(provenance, "source_subsystem", "STRATEGY")
    return str(getattr(value, "value", value))


def _references(traces: Iterable[object]) -> tuple[SourceReference, ...]:
    refs: list[SourceReference] = []
    for trace in traces:
        for node in getattr(trace, "nodes", ()) or ():
            provenance = getattr(node, "provenance", None)
            if provenance is not None:
                refs.append(SourceReference(
                    sourceSubsystem=_subsystem(provenance),
                    sourceType=str(getattr(provenance, "source_type", "TRACE_EVENT")),
                    sourceIdentifier=str(getattr(provenance, "source_identifier", "")),
                    timestamp=str(getattr(provenance, "timestamp", None)) if getattr(provenance, "timestamp", None) is not None else None,
                    linkageMethod=str(getattr(provenance, "linkage_method", "EVIDENCE_REFERENCE")),
                    confidence=str(getattr(provenance, "confidence", "")) if getattr(provenance, "confidence", None) is not None else None,
                ))
    return dedupe_references(refs)


def _evaluate_trace(trace: object, observations: list[SpecialistObservation], statuses: list[SpecialistStatus]):
    no_trade = getattr(trace, "no_trade", None)
    decision = getattr(trace, "decision", None)
    rejection = getattr(trace, "rejection", None)
    execution_attempt = getattr(trace, "execution_attempt", None)
    orders = getattr(trace, "orders", ()) or ()

    # Entry gate rejection after a strategy decision/intent.
    if rejection is not None:
        observations.append(SpecialistObservation(
            code="ENTRY_REJECTED_AFTER_STRATEGY", severity=SpecialistSeverity.WARNING,
            detail="A strategy decision was produced but a downstream gate rejected entry.",
        ))
        statuses.append(SpecialistStatus.WARNING)
        return

    # Deliberate no-trade.
    if no_trade is not None:
        status = _node_status(no_trade)
        supported = _is_suppressed(status, no_trade)
        if supported:
            observations.append(SpecialistObservation(
                code="STRATEGY_SUPPRESSED", severity=SpecialistSeverity.INFO,
                detail="Strategy produced a deliberate suppression/no-trade.",
            ))
        else:
            observations.append(SpecialistObservation(
                code="STRATEGY_NO_TRADE", severity=SpecialistSeverity.INFO,
                detail="Strategy produced a deliberate no-trade holding decision.",
            ))
        return

    # Explicit directional decision.
    if decision is not None and _node_status(decision) in _BUY_SELL:
        observations.append(SpecialistObservation(
            code="STRATEGY_DECISION_PRESENT", severity=SpecialistSeverity.INFO,
            detail=f"Strategy produced a directional decision: {_node_status(decision)}.",
        ))
        statuses.append(SpecialistStatus.HEALTHY)
        if execution_attempt is None and not orders:
            observations.append(SpecialistObservation(
                code="DECISION_EXECUTION_MISMATCH", severity=SpecialistSeverity.WARNING,
                detail="Strategy decision has no matching execution attempt evidence.",
            ))
            statuses.append(SpecialistStatus.WARNING)
        return

    if decision is not None:
        observations.append(SpecialistObservation(
            code="STRATEGY_NO_TRADE", severity=SpecialistSeverity.INFO,
            detail="Strategy decision evidence indicates holding rather than entry.",
        ))
        return


def _is_suppressed(status: str, node: object) -> bool:
    if status in _SUPPRESSED:
        return True
    for code in getattr(node, "reason_codes", ()) or ():
        value = getattr(code, "code", "") or ""
        if value and str(value).upper() in {
            "LIQUIDITY_INSTABILITY", "MOMENTUM_WARMUP", "DIRECTION_CONFLICT",
            "DIRECTION_NOT_CONFIRMED", "LOW_COMPOSITE_SCORE", "CONFLICTING_MOMENTUM",
            "WEAK_EDGE", "LOW_CONFIDENCE", "STRATEGY_HOLD", "STRATEGY_STATE_INVALID",
        }:
            return True
    return False


def evaluate_strategy(
    snapshot: ReadOnlySupervisorSnapshot,
    traces: tuple[object, ...],
    now: datetime,
) -> SpecialistFinding:
    observations: list[SpecialistObservation] = []
    statuses: list[SpecialistStatus] = []
    references = list(_references(traces))
    warnings: list[str] = []

    decision_domain = snapshot.decision
    decision_status = (decision_domain.status or "").upper()
    reasons = list(_reason_codes(traces))

    if traces:
        for trace in traces:
            if trace is None:
                continue
            _evaluate_trace(trace, observations, statuses)
    else:
        if decision_status and decision_status not in {"UNKNOWN", "NA", "N/A"}:
            references.append(SourceReference(
                sourceSubsystem="BOT_MANAGER_STATUS", sourceType="SUPERVISOR_SNAPSHOT:decision",
                sourceIdentifier=decision_domain.evaluatedAt.isoformat() if decision_domain.evaluatedAt else "decision",
                timestamp=decision_domain.evaluatedAt.isoformat() if decision_domain.evaluatedAt else None,
                linkageMethod="SUPERVISOR_SNAPSHOT",
            ))
            if decision_status in _BUY_SELL:
                observations.append(SpecialistObservation(
                    code="STRATEGY_DECISION_PRESENT", severity=SpecialistSeverity.INFO,
                    detail=f"Current strategy decision is directional: {decision_status}.",
                ))
                statuses.append(SpecialistStatus.HEALTHY)
            elif decision_status in _ENTRY_BLOCK:
                observations.append(SpecialistObservation(
                    code="ENTRY_REJECTED_AFTER_STRATEGY", severity=SpecialistSeverity.WARNING,
                    detail="Current strategy decision was blocked at a downstream gate.",
                ))
                statuses.append(SpecialistStatus.WARNING)
            elif decision_status in _SUPPRESSED:
                observations.append(SpecialistObservation(
                    code="STRATEGY_SUPPRESSED", severity=SpecialistSeverity.INFO,
                    detail="Current strategy decision is suppressed.",
                ))
            elif decision_status in _HOLD or decision_status in {"READY"}:
                observations.append(SpecialistObservation(
                    code="STRATEGY_NO_TRADE", severity=SpecialistSeverity.INFO,
                    detail="Current strategy decision is holding; no trade.",
                ))
            else:
                observations.append(SpecialistObservation(
                    code="STRATEGY_DECISION_PRESENT", severity=SpecialistSeverity.INFO,
                    detail=f"Current strategy decision is {decision_status}.",
                ))
                statuses.append(SpecialistStatus.HEALTHY)
        else:
            observations.append(SpecialistObservation(
                code="DECISION_EVIDENCE_MISSING", severity=SpecialistSeverity.UNKNOWN,
                detail="No strategy decision evidence is available.",
            ))
            statuses.append(SpecialistStatus.UNAVAILABLE)
            warnings.append("DECISION_EVIDENCE_MISSING")

    if decision_domain.freshness in {Freshness.MISSING, Freshness.STALE}:
        observations.append(SpecialistObservation(
            code="DECISION_EVIDENCE_UNRELIABLE", severity=SpecialistSeverity.WARNING,
            detail=f"Strategy decision authority is {decision_domain.freshness.value}.",
        ))
        statuses.append(SpecialistStatus.WARNING)
        warnings.append(f"DECISION_EVIDENCE_{decision_domain.freshness.value}")

    if not observations:
        observations.append(SpecialistObservation(
            code="DECISION_EVIDENCE_MISSING", severity=SpecialistSeverity.UNKNOWN,
            detail="No strategy decision evidence is available.",
        ))
        statuses.append(SpecialistStatus.UNAVAILABLE)
        warnings.append("DECISION_EVIDENCE_MISSING")

    if statuses:
        status = max(statuses, key=lambda item: {
            SpecialistStatus.HEALTHY: 0, SpecialistStatus.WARNING: 1,
            SpecialistStatus.UNKNOWN: 2, SpecialistStatus.UNAVAILABLE: 3,
            SpecialistStatus.CRITICAL: 4,
        }[item])
    else:
        status = SpecialistStatus.HEALTHY

    sev_values = [obs.severity for obs in observations]
    if any(sev is SpecialistSeverity.CRITICAL for sev in sev_values):
        severity = SpecialistSeverity.CRITICAL
    elif any(sev is SpecialistSeverity.UNKNOWN for sev in sev_values):
        severity = SpecialistSeverity.UNKNOWN
    elif any(sev is SpecialistSeverity.WARNING for sev in sev_values):
        severity = SpecialistSeverity.WARNING
    else:
        severity = SpecialistSeverity.INFO

    confidence = 0.0 if not traces else min(1.0, sum(1 for t in traces if t is not None) / len(traces))
    if not traces and decision_status:
        confidence = 0.5
    elif not traces:
        confidence = 0.0

    summary = f"Strategy evaluated as {status.value}."
    return SpecialistFinding(
        specialistId=SPECIALIST_ID,
        domain=DOMAIN,
        status=status,
        severity=severity,
        summary=summary,
        findings=merge_observations(observations),
        reasonCodes=dedupe_reason_codes(reasons),
        sourceReferences=dedupe_references(references),
        evidenceTimestamp=decision_domain.evaluatedAt or snapshot.capturedAt,
        freshness=decision_domain.freshness,
        confidence=round(confidence, 4),
        warnings=unique_warnings(warnings),
        generatedAt=now,
    )
