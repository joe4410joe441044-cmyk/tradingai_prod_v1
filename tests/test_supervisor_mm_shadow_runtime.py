from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.supervisor.contracts import (
    CapitalSource,
    DomainSnapshot,
    Freshness,
    MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot,
    SnapshotWarning,
)
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.mm_shadow_runtime import (
    MMShadowProviderStatus,
    MMShadowRuntimeStatus,
    MMShadowValidationStatus,
    evaluate_mm_shadow,
)
from backend.supervisor.provider import (
    ProviderAvailability,
    ProviderIdentity,
    ProviderResult,
)
from backend.supervisor import evaluate_mm_shadow as public_evaluate_mm_shadow


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def snapshot(
    *,
    overall=Freshness.FRESH,
    mm_freshness=Freshness.FRESH,
    authority_fresh=True,
    evaluated_at=NOW,
    ruin_guard="PASS",
    capital_source=CapitalSource.PAPER,
    warnings=(),
):
    domain = DomainSnapshot(freshness=Freshness.FRESH, evaluatedAt=NOW)
    mm = MoneyManagementSnapshot(
        capitalAuthority="MONEY_MANAGEMENT",
        capitalSource=capital_source,
        equity=Decimal("1000.123456789"),
        availableCapital=Decimal("900.123456789"),
        mmMode="MANUAL",
        mmRegime="NORMAL",
        riskBudget=Decimal("10.123456789"),
        remainingExposure=Decimal("75.123456789"),
        remainingPositionCapacity=Decimal("1"),
        ruinGuardStatus=ruin_guard,
        compoundingEnabled=False,
        executionEntryAllowed=False,
        policyVersion="1.0",
        evaluatedAt=evaluated_at,
        authorityFresh=authority_fresh,
        drawdown=Decimal("1.123456789"),
        currentExposure=Decimal("25.123456789"),
        openPositionState="NONE",
        reasonCodes=("WITHIN_POLICY",),
        freshness=mm_freshness,
    )
    return ReadOnlySupervisorSnapshot(
        capturedAt=NOW,
        overallFreshness=overall,
        bot=domain,
        loop=domain,
        trade=domain,
        governance=domain,
        emergency=domain,
        execution=domain,
        market=domain,
        decision=domain,
        health=domain,
        moneyManagement=mm,
        warnings=warnings,
    )


def output(
    *,
    state="CAUTION",
    direction="MAINTAIN",
    multiplier="0.8",
    condition="DEGRADED",
    reason="bounded observation",
    source_at=NOW,
    assessed_at=NOW,
):
    return {
        "schemaVersion": 1,
        "agent": "MM_SUPERVISOR",
        "mode": "SHADOW",
        "assessmentState": state,
        "recommendedRiskDirection": direction,
        "recommendedRiskMultiplier": multiplier,
        "capitalCondition": condition,
        "confidence": 0.8,
        "reasons": [reason],
        "uncertainties": [],
        "recoveryConditions": [],
        "sourceEvaluatedAt": source_at,
        "assessedAt": assessed_at,
    }


class FakeStructuredProvider:
    def __init__(self, value, *, availability=ProviderAvailability.AVAILABLE):
        self.value = value
        self._availability = availability
        self.requests = []

    @property
    def identity(self):
        return ProviderIdentity("fake-structured-provider", "1.0")

    @property
    def availability(self):
        return self._availability

    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        self.requests.append((deepcopy(input_data), output_contract, timeout_seconds))
        return ProviderResult(self.value)


class TimeoutProvider(FakeStructuredProvider):
    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        raise TimeoutError("traceback SECRET_VALUE_MUST_NOT_LEAK")


class ExceptionProvider(FakeStructuredProvider):
    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        raise RuntimeError("traceback SECRET_VALUE_MUST_NOT_LEAK")


@pytest.mark.parametrize(
    "state,direction,multiplier,condition",
    [
        ("NORMAL", "MAINTAIN", "1", "HEALTHY"),
        ("CAUTION", "REDUCE", "0.8", "DEGRADED"),
        ("DEFENSIVE", "PAUSE", None, "CRITICAL"),
        ("LOCKED", "PAUSE", "0", "CRITICAL"),
    ],
)
def test_valid_shadow_assessments_complete_without_operational_effect(
    state, direction, multiplier, condition
):
    source = snapshot()
    before = source.model_dump(mode="python")
    provider = FakeStructuredProvider(output(
        state=state,
        direction=direction,
        multiplier=multiplier,
        condition=condition,
    ))
    result = evaluate_mm_shadow(source, provider, NOW)

    assert source.model_dump(mode="python") == before
    assert result.status is MMShadowRuntimeStatus.COMPLETED
    assert result.providerStatus is MMShadowProviderStatus.VALID
    assert result.validationStatus is MMShadowValidationStatus.VALID
    assert result.assessment is not None
    assert result.assessment.mode.value == "SHADOW"
    assert result.operationalEffect == "NONE"
    assert result.configurationChanged is False
    assert result.riskChanged is False
    assert result.quantityChanged is False
    assert result.orderAction == "NONE"
    request, contract, timeout = provider.requests[0]
    assert request["agentId"] == "MM_SUPERVISOR"
    assert request["mode"] == "SHADOW"
    assert request["context"]["equity"] == "1000.123456789"
    assert "bot" not in request["context"]
    assert contract.__name__ == "MMSupervisorAssessment"
    assert timeout == 5.0


@pytest.mark.parametrize("mode", ["ADVISORY", "ACTIVE"])
def test_provider_cannot_promote_shadow_mode(mode):
    value = output()
    value["mode"] = mode
    result = evaluate_mm_shadow(snapshot(), FakeStructuredProvider(value), NOW)
    assert result.status is MMShadowRuntimeStatus.FAILED_CLOSED
    assert result.assessment is None
    assert result.failureCode is SupervisorFailureCode.MODE_NOT_ALLOWED
    assert result.operationalEffect == "NONE"


@pytest.mark.parametrize(
    "freshness,expected",
    [
        (Freshness.STALE, SupervisorFailureCode.INPUT_STALE),
        (Freshness.MISSING, SupervisorFailureCode.INPUT_MISSING),
        (Freshness.CONFLICTED, SupervisorFailureCode.INPUT_CONFLICTED),
        (Freshness.UNKNOWN, SupervisorFailureCode.INPUT_INVALID),
    ],
)
def test_nonfresh_context_rejects_risk_increase_without_rewriting(freshness, expected):
    result = evaluate_mm_shadow(
        snapshot(overall=freshness, mm_freshness=freshness),
        FakeStructuredProvider(output(
            state="GROWTH",
            direction="INCREASE_WITHIN_POLICY",
            multiplier="1.1",
            condition="HEALTHY",
        )),
        NOW,
    )
    assert result.status is MMShadowRuntimeStatus.FAILED_CLOSED
    assert result.assessment is None
    assert result.failureCode is expected


@pytest.mark.parametrize(
    "source,provider_output,expected",
    [
        (
            snapshot(authority_fresh=False),
            output(direction="INCREASE_WITHIN_POLICY", multiplier="1.1"),
            SupervisorFailureCode.INPUT_MISSING,
        ),
        (
            snapshot(evaluated_at=None),
            output(direction="INCREASE_WITHIN_POLICY", multiplier="1.1"),
            SupervisorFailureCode.INPUT_MISSING,
        ),
        (
            snapshot(ruin_guard="UNAVAILABLE"),
            output(state="GROWTH", condition="HEALTHY"),
            SupervisorFailureCode.INPUT_MISSING,
        ),
        (
            snapshot(),
            output(direction="MAINTAIN", multiplier="1.0000000001"),
            SupervisorFailureCode.ACTION_PROHIBITED,
        ),
    ],
)
def test_authority_gaps_and_missing_policy_ceiling_reject_unsafe_output(
    source, provider_output, expected
):
    if source.moneyManagement.evaluatedAt is None:
        provider_output["sourceEvaluatedAt"] = source.capturedAt
    result = evaluate_mm_shadow(source, FakeStructuredProvider(provider_output), NOW)
    assert result.assessment is None
    assert result.failureCode is expected


def test_safe_unknown_assessment_can_describe_missing_authority_without_invention():
    source = snapshot(evaluated_at=None, authority_fresh=False, ruin_guard="UNAVAILABLE")
    mm = source.moneyManagement.model_copy(update={
        "capitalAuthority": None,
        "equity": None,
        "availableCapital": None,
        "riskBudget": None,
        "remainingExposure": None,
        "remainingPositionCapacity": None,
    })
    source = source.model_copy(update={"moneyManagement": mm})
    result = evaluate_mm_shadow(
        source,
        FakeStructuredProvider(output(
            state="UNKNOWN",
            direction="PAUSE",
            multiplier=None,
            condition="UNKNOWN",
            source_at=source.capturedAt,
        )),
        NOW,
    )
    assert result.status is MMShadowRuntimeStatus.COMPLETED
    assert result.assessment.assessmentState.value == "UNKNOWN"
    assert result.operationalEffect == "NONE"


def test_provider_absence_unavailability_timeout_and_exception_fail_closed():
    cases = (
        (None, SupervisorFailureCode.PROVIDER_UNAVAILABLE, MMShadowProviderStatus.UNAVAILABLE),
        (
            FakeStructuredProvider(output(), availability=ProviderAvailability.UNAVAILABLE),
            SupervisorFailureCode.PROVIDER_UNAVAILABLE,
            MMShadowProviderStatus.UNAVAILABLE,
        ),
        (TimeoutProvider(output()), SupervisorFailureCode.PROVIDER_TIMEOUT, MMShadowProviderStatus.TIMEOUT),
        (ExceptionProvider(output()), SupervisorFailureCode.FAIL_CLOSED, MMShadowProviderStatus.INVALID),
    )
    for provider, code, status in cases:
        result = evaluate_mm_shadow(snapshot(), provider, NOW)
        assert result.status is MMShadowRuntimeStatus.FAILED_CLOSED
        assert result.assessment is None
        assert result.failureCode is code
        assert result.providerStatus is status
        assert result.operationalEffect == "NONE"
        assert "SECRET_VALUE_MUST_NOT_LEAK" not in result.stable_json()
        assert "traceback" not in result.stable_json().lower()


def test_non_structured_json_like_output_is_invalid_and_runtime_has_no_commands():
    result = evaluate_mm_shadow(
        snapshot(), FakeStructuredProvider('{"mode":"SHADOW"}'), NOW
    )
    assert result.assessment is None
    assert result.failureCode is SupervisorFailureCode.OUTPUT_INVALID
    assert public_evaluate_mm_shadow is evaluate_mm_shadow
    forbidden = {
        "submit_order", "cancel_order", "update_configuration", "recover",
        "unlock_emergency", "change_risk", "change_quantity",
    }
    assert forbidden.isdisjoint(dir(result))


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"extra": "rejected"}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"assessmentState": "NOT_A_STATE"}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"recommendedRiskMultiplier": "NaN"}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"recommendedRiskMultiplier": "Infinity"}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"sourceEvaluatedAt": datetime(2026, 8, 12, 12)}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"reason": "risk changed by supervisor"}, SupervisorFailureCode.ACTION_PROHIBITED),
    ],
)
def test_invalid_schema_and_forbidden_claims_are_never_adopted(change, expected):
    value = output()
    if "reason" in change:
        value["reasons"] = [change["reason"]]
    else:
        value.update(change)
    result = evaluate_mm_shadow(snapshot(), FakeStructuredProvider(value), NOW)
    assert result.status is MMShadowRuntimeStatus.FAILED_CLOSED
    assert result.assessment is None
    assert result.failureCode is expected
    assert result.validationStatus is MMShadowValidationStatus.INVALID


def test_provider_reported_timeout_and_critical_conflict_are_stable():
    class ReportedTimeout(FakeStructuredProvider):
        def generate_structured_output(self, input_data, output_contract, timeout_seconds):
            return ProviderResult(None, SupervisorFailureCode.PROVIDER_TIMEOUT)

    timeout = evaluate_mm_shadow(snapshot(), ReportedTimeout(None), NOW)
    assert timeout.failureCode is SupervisorFailureCode.PROVIDER_TIMEOUT

    conflict = SnapshotWarning(
        code=SupervisorFailureCode.INPUT_CONFLICTED,
        domain="moneyManagement",
        field="capitalSource",
        message="capital sources conflict",
        sourceEvaluatedAt=NOW,
    )
    result = evaluate_mm_shadow(
        snapshot(warnings=(conflict,)),
        FakeStructuredProvider(output(state="NORMAL", condition="HEALTHY")),
        NOW,
    )
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED


def test_non_mm_critical_conflict_is_rejected_even_if_snapshot_freshness_is_inconsistent():
    conflict = SnapshotWarning(
        code=SupervisorFailureCode.INPUT_CONFLICTED,
        domain="governance",
        field="mode",
        message="governance authorities conflict",
        sourceEvaluatedAt=NOW,
    )
    result = evaluate_mm_shadow(
        snapshot(warnings=(conflict,)),
        FakeStructuredProvider(output(state="NORMAL", condition="HEALTHY")),
        NOW,
    )
    assert result.assessment is None
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED


def test_same_input_and_provider_output_produce_same_result_and_audit_digest():
    first = evaluate_mm_shadow(snapshot(), FakeStructuredProvider(output()), NOW)
    second = evaluate_mm_shadow(snapshot(), FakeStructuredProvider(output()), NOW)
    assert first == second
    assert first.stable_json() == second.stable_json()
    assert first.auditEvent.assessmentDigest == second.auditEvent.assessmentDigest
