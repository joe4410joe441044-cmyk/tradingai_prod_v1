"""Execution Specialist: deterministic interpretation of execution evidence.

The specialist reads the authoritative read-only execution evidence and the
D-5 INFORMATION_ONLY ``UnifiedTradingTrace`` linkage.  It never retries an
order, cancels an order, mutates a position, or touches the exchange.
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
from .severity import worst_status

SPECIALIST_ID = "EXECUTION"
DOMAIN = "EXECUTION"

_REJECTED_STATUSES = frozenset({"REJECTED", "EXCHANGE_REJECTED", "CANCELED"})
_FAILED_STATUSES = frozenset({"FAILED", "ERROR", "EXCHANGE_ERROR"})
_PENDING_STATES = frozenset({"PENDING", "SUBMITTED", "OPEN", "PARTIALLY_FILLED"})
_RUNNING_BOT = frozenset({"RUNNING", "STARTED", "ACTIVE"})


def _reason_codes(traces: Iterable[object]) -> tuple[str, ...]:
    codes: list[str] = []
    for trace in traces:
        for code in getattr(trace, "reason_codes", ()) or ():
            value = getattr(code, "code", None) or getattr(code, "reason_code", None)
            if value:
                codes.append(str(value))
    return dedupe_reason_codes(codes)


def _subsystem(provenance: object) -> str:
    value = getattr(provenance, "source_subsystem", "EXECUTION")
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


def _trace_status(completeness: object) -> SpecialistStatus:
    from backend.runtime.unified_trace import TraceCompleteness

    return {
        TraceCompleteness.COMPLETE: SpecialistStatus.HEALTHY,
        TraceCompleteness.PARTIAL: SpecialistStatus.WARNING,
        TraceCompleteness.AMBIGUOUS: SpecialistStatus.UNKNOWN,
        TraceCompleteness.UNAVAILABLE: SpecialistStatus.UNAVAILABLE,
    }.get(completeness, SpecialistStatus.UNKNOWN)


def evaluate_execution(
    snapshot: ReadOnlySupervisorSnapshot,
    traces: tuple[object, ...],
    now: datetime,
) -> SpecialistFinding:
    observations: list[SpecialistObservation] = []
    references: list[SourceReference] = list(_references(traces))
    warnings: list[str] = []
    statuses: list[SpecialistStatus] = []

    execution = snapshot.execution
    runtime_state = (execution.authoritativeRuntimeState or "").upper()
    pending_state = (execution.pendingOrderState or "").upper()

    if not traces:
        observations.append(SpecialistObservation(
            code="EXECUTION_TRACE_UNAVAILABLE", severity=SpecialistSeverity.UNKNOWN,
            detail="No D-5 execution trace evidence is available for evaluation.",
        ))
        warnings.append("EXECUTION_TRACE_UNAVAILABLE")
        statuses.append(SpecialistStatus.UNAVAILABLE)
    else:
        complete_count = 0
        for trace in traces:
            if trace is None:
                continue
            completeness = getattr(trace, "completeness", None)
            statuses.append(_trace_status(completeness))
            if completeness is not None:
                name = getattr(completeness, "value", str(completeness))
                if name == "COMPLETE":
                    complete_count += 1
                    observations.append(SpecialistObservation(
                        code="EXECUTION_TRACE_COMPLETE", severity=SpecialistSeverity.INFO,
                        detail="Execution trace is complete for the decision span.",
                    ))
                elif name == "PARTIAL":
                    observations.append(SpecialistObservation(
                        code="EXECUTION_TRACE_PARTIAL", severity=SpecialistSeverity.WARNING,
                        detail="Execution trace is partial; some evidence is missing.",
                    ))
                elif name == "AMBIGUOUS":
                    observations.append(SpecialistObservation(
                        code="EXECUTION_TRACE_AMBIGUOUS", severity=SpecialistSeverity.UNKNOWN,
                        detail="Execution trace linkage is ambiguous across decisions.",
                    ))
                elif name == "UNAVAILABLE":
                    observations.append(SpecialistObservation(
                        code="EXECUTION_TRACE_UNAVAILABLE", severity=SpecialistSeverity.UNKNOWN,
                        detail="Execution trace evidence is unavailable.",
                    ))

            attempt = getattr(trace, "execution_attempt", None)
            if attempt is not None:
                attempt_status = (getattr(attempt, "status", "") or "").upper()
                if attempt_status in _REJECTED_STATUSES:
                    observations.append(SpecialistObservation(
                        code="EXECUTION_REJECTED", severity=SpecialistSeverity.CRITICAL,
                        detail=f"Execution attempt was rejected: {attempt_status}.",
                    ))
                    statuses.append(SpecialistStatus.CRITICAL)
                elif attempt_status in _FAILED_STATUSES:
                    observations.append(SpecialistObservation(
                        code="EXECUTION_FAILED", severity=SpecialistSeverity.CRITICAL,
                        detail=f"Execution attempt failed: {attempt_status}.",
                    ))
                    statuses.append(SpecialistStatus.CRITICAL)

            orders = getattr(trace, "orders", ()) or ()
            fills = getattr(trace, "fills", ()) or ()
            position = getattr(trace, "position", None)
            result = getattr(trace, "trade_result", None)
            if orders and not fills and position is None:
                observations.append(SpecialistObservation(
                    code="ORDER_WITHOUT_CONFIRMED_FILL", severity=SpecialistSeverity.WARNING,
                    detail="Order evidence exists without a confirmed fill or position.",
                ))
                statuses.append(SpecialistStatus.WARNING)
            if fills and position is None:
                observations.append(SpecialistObservation(
                    code="POSITION_EVIDENCE_MISSING", severity=SpecialistSeverity.WARNING,
                    detail="Fill evidence exists without corresponding position evidence.",
                ))
                statuses.append(SpecialistStatus.WARNING)
            if position is not None and result is None and getattr(trace, "exit", None) is None:
                observations.append(SpecialistObservation(
                    code="RESULT_EVIDENCE_MISSING", severity=SpecialistSeverity.WARNING,
                    detail="Position evidence exists without a closed trade result.",
                ))
                statuses.append(SpecialistStatus.WARNING)
        if traces and complete_count == 0:
            warnings.append("EXECUTION_TRACE_NOT_COMPLETE")

    bot_status = str(snapshot.bot.status or "").upper()
    if runtime_state in {"STOPPED"} and bot_status in _RUNNING_BOT:
        observations.append(SpecialistObservation(
            code="EXECUTION_RUNTIME_STOPPED", severity=SpecialistSeverity.CRITICAL,
            detail="Execution runtime is stopped while the bot reports running.",
        ))
        statuses.append(SpecialistStatus.CRITICAL)

    if runtime_state in {"UNKNOWN", "UNAVAILABLE"} and execution.freshness is not Freshness.FRESH:
        observations.append(SpecialistObservation(
            code="EXECUTION_RUNTIME_UNKNOWN", severity=SpecialistSeverity.UNKNOWN,
            detail="Execution runtime authority is unknown or unavailable.",
        ))
        statuses.append(SpecialistStatus.UNKNOWN)

    if pending_state in _PENDING_STATES:
        references.extend([
            SourceReference(
                sourceSubsystem="BOT_MANAGER_STATUS", sourceType="SUPERVISOR_SNAPSHOT:execution",
                sourceIdentifier=execution.evaluatedAt.isoformat() if execution.evaluatedAt else "execution",
                timestamp=execution.evaluatedAt.isoformat() if execution.evaluatedAt else None,
                linkageMethod="SUPERVISOR_SNAPSHOT",
            )
        ])
        observations.append(SpecialistObservation(
            code="EXECUTION_ORDER_PENDING", severity=SpecialistSeverity.INFO,
            detail="An execution order is pending confirmation.",
        ))

    if execution.freshness in {Freshness.MISSING, Freshness.STALE, Freshness.CONFLICTED}:
        warnings.append(f"EXECUTION_EVIDENCE_{execution.freshness.value}")
        observations.append(SpecialistObservation(
            code="EXECUTION_EVIDENCE_UNRELIABLE", severity=SpecialistSeverity.WARNING,
            detail=f"Execution authority evidence is {execution.freshness.value}.",
        ))
        statuses.append(SpecialistStatus.WARNING)

    if not statuses:
        status = SpecialistStatus.UNKNOWN
    else:
        status = worst_status(statuses)

    severity_severities = [item.severity for item in observations]
    if any(sev is SpecialistSeverity.CRITICAL for sev in severity_severities):
        severity = SpecialistSeverity.CRITICAL
    elif any(sev is SpecialistSeverity.UNKNOWN for sev in severity_severities):
        severity = SpecialistSeverity.UNKNOWN
    elif any(sev is SpecialistSeverity.WARNING for sev in severity_severities):
        severity = SpecialistSeverity.WARNING
    else:
        severity = SpecialistSeverity.INFO

    if not traces and execution.freshness is Freshness.MISSING:
        status = SpecialistStatus.UNAVAILABLE
        severity = SpecialistSeverity.UNKNOWN

    confidence = 0.0 if not traces else min(1.0, complete_count / len([t for t in traces if t is not None]))

    summary = f"Execution evaluated as {status.value}."
    return SpecialistFinding(
        specialistId=SPECIALIST_ID,
        domain=DOMAIN,
        status=status,
        severity=severity,
        summary=summary,
        findings=merge_observations(observations),
        reasonCodes=_reason_codes(traces),
        sourceReferences=dedupe_references(references),
        evidenceTimestamp=execution.evaluatedAt or snapshot.capturedAt,
        freshness=execution.freshness,
        confidence=round(confidence, 4),
        warnings=unique_warnings(warnings),
        generatedAt=now,
    )
