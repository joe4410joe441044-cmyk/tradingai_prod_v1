from datetime import datetime, timedelta, timezone

import pytest

from backend.supervisor.contracts import (
    DomainSnapshot, Freshness, MasterSupervisorDecision, MMSupervisorAssessment,
    MoneyManagementSnapshot, ReadOnlySupervisorSnapshot,
)
from backend.supervisor.failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from backend.supervisor.provider import ProviderResult, require_provider, validate_provider_result
from backend.supervisor.validation import validate_master_decision, validate_mm_assessment


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def mm(direction="MAINTAIN", state="CAUTION", condition="DEGRADED", source=NOW):
    return MMSupervisorAssessment(
        assessmentState=state, recommendedRiskDirection=direction,
        recommendedRiskMultiplier="0.8", capitalCondition=condition, confidence=0.7,
        reasons=("policy",), sourceEvaluatedAt=source, assessedAt=NOW,
    )


def snapshot(freshness=Freshness.FRESH, critical=Freshness.FRESH):
    domain = DomainSnapshot(freshness=critical, evaluatedAt=NOW)
    return ReadOnlySupervisorSnapshot(
        capturedAt=NOW, overallFreshness=freshness, bot=domain, loop=domain, trade=domain,
        governance=domain, emergency=domain, execution=domain, market=domain,
        decision=domain, health=domain,
        moneyManagement=MoneyManagementSnapshot(freshness=critical, evaluatedAt=NOW),
    )


def decision(direction="MAINTAIN", posture="CAUTION"):
    return MasterSupervisorDecision(
        overallPosture=posture, tradingRecommendation="CONTINUE_REDUCED",
        mmRecommendation={"riskDirection": direction, "riskMultiplier": "0.8"},
        humanAttention="REVIEW", summary="Cautious posture.", reasons=("policy",),
        sourceEvaluatedAt=NOW, decidedAt=NOW,
    )


def test_fresh_inputs_allow_validation():
    validate_mm_assessment(mm(), Freshness.FRESH, now=NOW)
    validate_master_decision(decision(), snapshot(), now=NOW)


@pytest.mark.parametrize("freshness", [
    Freshness.STALE, Freshness.MISSING, Freshness.CONFLICTED, Freshness.UNKNOWN,
])
def test_non_fresh_inputs_forbid_risk_increase(freshness):
    with pytest.raises(SupervisorBoundaryError):
        validate_mm_assessment(mm("INCREASE_WITHIN_POLICY"), freshness, now=NOW)
    with pytest.raises(SupervisorBoundaryError):
        validate_master_decision(decision("INCREASE_WITHIN_POLICY"), snapshot(freshness), now=NOW)


def test_future_mm_authority_timestamp_is_invalid():
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_mm_assessment(mm(source=NOW + timedelta(seconds=1)), Freshness.FRESH, now=NOW)
    assert caught.value.code is SupervisorFailureCode.TIMESTAMP_INVALID


@pytest.mark.parametrize("posture", ["NORMAL", "GROWTH"])
def test_critical_missing_forbids_normal_and_growth(posture):
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_master_decision(decision(posture=posture), snapshot(critical=Freshness.MISSING), now=NOW)
    assert caught.value.code is SupervisorFailureCode.INPUT_MISSING


def test_unavailable_mm_authority_forbids_healthy_or_growth():
    with pytest.raises(SupervisorBoundaryError):
        validate_mm_assessment(mm(condition="HEALTHY"), Freshness.MISSING, now=NOW)
    with pytest.raises(SupervisorBoundaryError):
        validate_mm_assessment(mm(state="GROWTH"), Freshness.STALE, now=NOW)


def test_provider_absence_timeout_and_invalid_output_are_stable_failures():
    with pytest.raises(SupervisorBoundaryError) as caught:
        require_provider(None)
    assert caught.value.code is SupervisorFailureCode.PROVIDER_UNAVAILABLE
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_provider_result(ProviderResult(None, SupervisorFailureCode.PROVIDER_TIMEOUT))
    assert caught.value.code is SupervisorFailureCode.PROVIDER_TIMEOUT
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_provider_result(ProviderResult(None))
    assert caught.value.code is SupervisorFailureCode.OUTPUT_INVALID
