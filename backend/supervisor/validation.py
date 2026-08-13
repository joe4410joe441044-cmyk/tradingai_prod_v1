"""Cross-contract, failure-safe validation rules."""

from datetime import datetime, timezone

from .contracts import (
    CapitalCondition, Freshness, MasterSupervisorDecision, MMSupervisorAssessment,
    ReadOnlySupervisorSnapshot, RiskDirection, SupervisorState,
)
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode


UNSAFE_FRESHNESS = frozenset({Freshness.STALE, Freshness.MISSING, Freshness.CONFLICTED, Freshness.UNKNOWN})
CRITICAL_DOMAINS = ("governance", "emergency", "execution", "health", "moneyManagement")


def _freshness_code(freshness: Freshness) -> SupervisorFailureCode:
    return {
        Freshness.STALE: SupervisorFailureCode.INPUT_STALE,
        Freshness.MISSING: SupervisorFailureCode.INPUT_MISSING,
        Freshness.CONFLICTED: SupervisorFailureCode.INPUT_CONFLICTED,
        Freshness.UNKNOWN: SupervisorFailureCode.INPUT_INVALID,
    }.get(freshness, SupervisorFailureCode.FAIL_CLOSED)


def validate_mm_assessment(
    assessment: MMSupervisorAssessment, authority_freshness: Freshness, *, now: datetime | None = None
) -> None:
    current = now or datetime.now(timezone.utc)
    if assessment.sourceEvaluatedAt > current:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.TIMESTAMP_INVALID, "MM authority timestamp is in the future"
        )
    if authority_freshness in UNSAFE_FRESHNESS:
        if assessment.recommendedRiskDirection is RiskDirection.INCREASE_WITHIN_POLICY:
            raise SupervisorBoundaryError(_freshness_code(authority_freshness), "risk increase requires fresh authority")
        if assessment.capitalCondition is CapitalCondition.HEALTHY or assessment.assessmentState is SupervisorState.GROWTH:
            raise SupervisorBoundaryError(
                _freshness_code(authority_freshness), "unavailable authority cannot produce a healthy/growth assessment"
            )


def validate_master_decision(
    decision: MasterSupervisorDecision, snapshot: ReadOnlySupervisorSnapshot, *, now: datetime | None = None
) -> None:
    current = now or datetime.now(timezone.utc)
    if decision.sourceEvaluatedAt > current or snapshot.capturedAt > current:
        raise SupervisorBoundaryError(SupervisorFailureCode.TIMESTAMP_INVALID, "source timestamp is in the future")
    critical = [getattr(snapshot, name).freshness for name in CRITICAL_DOMAINS]
    if any(value is Freshness.MISSING for value in critical) and decision.overallPosture in (
        SupervisorState.NORMAL, SupervisorState.GROWTH
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_MISSING, "critical missing input forbids NORMAL/GROWTH"
        )
    if snapshot.overallFreshness in UNSAFE_FRESHNESS and (
        decision.mmRecommendation.riskDirection is RiskDirection.INCREASE_WITHIN_POLICY
    ):
        raise SupervisorBoundaryError(
            _freshness_code(snapshot.overallFreshness), "risk increase requires fresh inputs"
        )
