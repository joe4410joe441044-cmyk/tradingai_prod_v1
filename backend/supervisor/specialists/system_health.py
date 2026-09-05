"""System Health Specialist: deterministic interpretation of runtime health.

The specialist is observation-only.  It evaluates the existing authoritative
read-only health evidence and never restarts a process, triggers recovery, or
mutates runtime state.  Systems that cannot be observed are reported as
UNAVAILABLE/UNKNOWN rather than healthy.
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
from .severity import worst_severity

SPECIALIST_ID = "SYSTEM_HEALTH"
DOMAIN = "SYSTEM_HEALTH"

_RUNNING_STATES = frozenset({"RUNNING", "STARTED", "ACTIVE"})
_OK_BACKEND = frozenset({"", "OK", "HEALTHY", "NORMAL"})


def _domain_reference(domain_name: str, snapshot: ReadOnlySupervisorSnapshot) -> SourceReference:
    domain = getattr(snapshot, domain_name, None)
    source = getattr(domain, "source", None) or "AUTHORITATIVE"
    evaluated_at = getattr(domain, "evaluatedAt", None)
    identifier = evaluated_at.isoformat() if evaluated_at is not None else domain_name
    return SourceReference(
        sourceSubsystem=str(source),
        sourceType=f"SUPERVISOR_SNAPSHOT:{domain_name}",
        sourceIdentifier=identifier,
        timestamp=evaluated_at.isoformat() if evaluated_at is not None else None,
        linkageMethod="SUPERVISOR_SNAPSHOT",
    )


def _evidence(observations: Iterable[SpecialistObservation]) -> tuple[SpecialistObservation, ...]:
    return merge_observations(observations)


def evaluate_system_health(
    snapshot: ReadOnlySupervisorSnapshot,
    now: datetime,
) -> SpecialistFinding:
    observations: list[SpecialistObservation] = []
    reasons: list[str] = []
    references: list[SourceReference] = []
    warnings: list[str] = []
    expected_signals: list[bool] = []

    health = snapshot.health
    health_observed = (
        health.freshness is not Freshness.MISSING
        and (health.runtimeHealthy is not None or health.backendStatus is not None)
    )
    expected_signals.append(health_observed)
    if health_observed:
        references.append(_domain_reference("health", snapshot))
        runtime_healthy = health.runtimeHealthy
        backend_status = (health.backendStatus or "").upper()
        if runtime_healthy is False:
            observations.append(SpecialistObservation(
                code="RUNTIME_UNHEALTHY", severity=SpecialistSeverity.CRITICAL,
                detail="Runtime health produced an unhealthy signal.",
            ))
        elif runtime_healthy is None and backend_status not in _OK_BACKEND:
            observations.append(SpecialistObservation(
                code="BACKEND_STATUS_DEGRADED", severity=SpecialistSeverity.WARNING,
                detail=f"Backend status is not healthy: {backend_status or 'UNKNOWN'}.",
            ))
        elif runtime_healthy is None:
            observations.append(SpecialistObservation(
                code="HEALTH_EVIDENCE_PARTIAL", severity=SpecialistSeverity.UNKNOWN,
                detail="Backend health is partially observed; runtime health is unavailable.",
            ))
    else:
        observations.append(SpecialistObservation(
            code="HEALTH_SOURCE_MISSING", severity=SpecialistSeverity.UNKNOWN,
            detail="No authoritative runtime health evidence is available.",
        ))
        warnings.append("SYSTEM_HEALTH_SOURCE_MISSING")

    loop = snapshot.loop
    loop_observed = loop.enabled is not None or loop.state is not None
    expected_signals.append(loop_observed)
    if loop_observed:
        references.append(_domain_reference("loop", snapshot))
    loop_state = (loop.state or "").upper()
    loop_enabled = loop.enabled
    if loop_enabled is True and loop_state not in _RUNNING_STATES and loop_state:
        observations.append(SpecialistObservation(
            code="LOOP_ENABLED_BUT_NOT_RUNNING", severity=SpecialistSeverity.WARNING,
            detail=f"Loop is enabled but reports '{loop_state}'.",
        ))
    elif loop_enabled is False and loop_state in _RUNNING_STATES:
        observations.append(SpecialistObservation(
            code="LOOP_DISABLED_CONFLICT", severity=SpecialistSeverity.WARNING,
            detail="Loop is disabled but reports a running state.",
        ))

    bot = snapshot.bot
    bot_status = (bot.status or "").upper()
    bot_observed = bool(bot_status)
    expected_signals.append(bot_observed)
    if bot_observed:
        references.append(_domain_reference("bot", snapshot))
    if bot_status and bot_status not in _RUNNING_STATES:
        observations.append(SpecialistObservation(
            code="BOT_STOPPED", severity=SpecialistSeverity.INFO,
            detail="Bot is not running; trading is suspended until started.",
        ))
    if bot_observed and loop_observed and bot_status in _RUNNING_STATES and loop_enabled is False:
        observations.append(SpecialistObservation(
            code="LOOP_STOPPED_WHILE_BOT_RUNNING", severity=SpecialistSeverity.WARNING,
            detail="Bot is running but the trading loop is disabled.",
        ))

    trade = snapshot.trade
    auto_trade = trade.autoTradeEnabled
    expected_signals.append(auto_trade is not None)
    if auto_trade is not None:
        references.append(_domain_reference("trade", snapshot))
    loop_is_running = bool(loop_enabled is True and loop_state in _RUNNING_STATES)
    if auto_trade is True and not loop_is_running:
        observations.append(SpecialistObservation(
            code="AUTO_TRADE_ENABLED_WHILE_LOOP_STOPPED", severity=SpecialistSeverity.CRITICAL,
            detail="Auto Trade is enabled but the trading loop is not running.",
        ))
        warnings.append("AUTO_TRADE_ENABLED_WHILE_LOOP_STOPPED")

    if snapshot.overallFreshness is not Freshness.FRESH:
        references.append(_domain_reference("health", snapshot))
    if snapshot.overallFreshness is Freshness.STALE:
        observations.append(SpecialistObservation(
            code="OVERALL_EVIDENCE_STALE", severity=SpecialistSeverity.WARNING,
            detail="Overall authoritative evidence is stale under the freshness policy.",
        ))
    elif snapshot.overallFreshness is Freshness.MISSING:
        observations.append(SpecialistObservation(
            code="OVERALL_EVIDENCE_MISSING", severity=SpecialistSeverity.UNKNOWN,
            detail="Overall authoritative evidence is missing.",
        ))
    elif snapshot.overallFreshness is Freshness.CONFLICTED:
        observations.append(SpecialistObservation(
            code="EVIDENCE_CONFLICTED", severity=SpecialistSeverity.UNKNOWN,
            detail="Overall authoritative evidence reports conflicting sources.",
        ))
    elif snapshot.overallFreshness is Freshness.UNKNOWN:
        observations.append(SpecialistObservation(
            code="EVIDENCE_FRESHNESS_UNKNOWN", severity=SpecialistSeverity.UNKNOWN,
            detail="Overall evidence freshness is unknown.",
        ))

    market = snapshot.market
    market_stale = market.marketStale
    market_ready = market.marketReady
    expected_signals.append(market_stale is not None or market_ready is not None)
    if market_stale is True:
        observations.append(SpecialistObservation(
            code="MARKET_DATA_STALE", severity=SpecialistSeverity.WARNING,
            detail="Market data is reported stale.",
        ))
    elif market_ready is False:
        observations.append(SpecialistObservation(
            code="MARKET_DATA_UNAVAILABLE", severity=SpecialistSeverity.WARNING,
            detail="Market data is observed but not ready.",
        ))

    observed = sum(1 for value in expected_signals if value)
    confidence = 0.0 if not expected_signals else min(1.0, observed / len(expected_signals))
    if observations:
        finding_severity = worst_severity(obs.severity for obs in observations)
    else:
        finding_severity = SpecialistSeverity.INFO

    observed_freshness = snapshot.overallFreshness
    if not health_observed and not bot_observed and not loop_observed:
        status = SpecialistStatus.UNAVAILABLE
    elif observed_freshness in {Freshness.MISSING, Freshness.UNKNOWN, Freshness.CONFLICTED}:
        status = SpecialistStatus.UNKNOWN
    elif not observations:
        # All expected evidence is present and fresh, with no finding thrown.
        status = SpecialistStatus.HEALTHY
    else:
        status = worst_status_from_observations(observations)

    summary = _summarize(status, observations)
    return SpecialistFinding(
        specialistId=SPECIALIST_ID,
        domain=DOMAIN,
        status=status,
        severity=finding_severity,
        summary=summary,
        findings=_evidence(observations),
        reasonCodes=dedupe_reason_codes(reasons),
        sourceReferences=dedupe_references(references),
        evidenceTimestamp=health.evaluatedAt or snapshot.capturedAt,
        freshness=snapshot.overallFreshness,
        confidence=round(confidence, 4),
        warnings=unique_warnings(warnings),
        generatedAt=now,
    )


def worst_status_from_observations(
    observations: Iterable[SpecialistObservation],
) -> SpecialistStatus:
    severities = [obs.severity for obs in observations]
    if any(sev is SpecialistSeverity.CRITICAL for sev in severities):
        return SpecialistStatus.CRITICAL
    if any(sev is SpecialistSeverity.WARNING for sev in severities):
        return SpecialistStatus.WARNING
    if any(sev is SpecialistSeverity.UNKNOWN for sev in severities):
        return SpecialistStatus.UNKNOWN
    if any(sev is SpecialistSeverity.INFO for sev in severities):
        return SpecialistStatus.HEALTHY
    return SpecialistStatus.UNKNOWN


def _summarize(status: SpecialistStatus, observations: Iterable[SpecialistObservation]) -> str:
    codes = [obs.code for obs in observations]
    if not codes:
        return "System health evidence is consistent and available."
    return f"System health evaluated as {status.value}: {', '.join(codes[:4])}."
