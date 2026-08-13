from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.supervisor.contracts import (
    CapitalSource,
    DomainSnapshot,
    FieldValueObservation,
    Freshness,
    InputValueState,
    MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot,
    SnapshotWarning,
)
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.master_shadow_runtime import (
    MasterShadowProviderStatus,
    MasterShadowRuntimeStatus,
    MasterShadowValidationStatus,
    evaluate_master_shadow,
)
from backend.supervisor.mm_shadow_runtime import evaluate_mm_shadow
from backend.supervisor.operator_constitution import TRADINGAI_OPERATOR_CONSTITUTION
from backend.supervisor.provider import ProviderAvailability, ProviderIdentity, ProviderResult


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
MM_NOW = NOW + timedelta(seconds=1)
MASTER_NOW = NOW + timedelta(seconds=2)


def snapshot(
    *,
    overall=Freshness.FRESH,
    governance_freshness=Freshness.FRESH,
    emergency_freshness=Freshness.FRESH,
    execution_freshness=Freshness.FRESH,
    health_freshness=Freshness.FRESH,
    mm_freshness=Freshness.FRESH,
    governance_enabled=True,
    emergency_locked=False,
    emergency_state="READY",
    runtime_healthy=True,
    warnings=(),
):
    bot = DomainSnapshot(freshness=Freshness.FRESH, evaluatedAt=NOW, status="RUNNING")
    loop = DomainSnapshot(
        freshness=Freshness.FRESH, evaluatedAt=NOW, enabled=True, state="RUNNING"
    )
    trade = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        selectedMode="PAPER",
        dryRun=True,
        autoTradeEnabled=False,
        realOrderAllowed=False,
    )
    governance = DomainSnapshot(
        freshness=governance_freshness,
        evaluatedAt=NOW,
        mode="PAPER",
        executionEnabled=governance_enabled,
        riskProfile="SAFE",
        fieldStates=(FieldValueObservation(
            field="executionEnabled", state=InputValueState.PRESENT
        ),),
    )
    emergency = DomainSnapshot(
        freshness=emergency_freshness,
        evaluatedAt=NOW,
        locked=emergency_locked,
        state=emergency_state,
    )
    execution = DomainSnapshot(
        freshness=execution_freshness,
        evaluatedAt=NOW,
        authoritativeRuntimeState="SYNCHRONIZED",
        synchronizationState="HEALTHY",
        pendingOrderState="NONE",
        realOrderAllowed=False,
    )
    market = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        activeSymbol="BTC-USDT",
        marketReady=True,
        marketStale=False,
        selectionMode="MANUAL",
    )
    decision = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        status="HOLD",
    )
    health = DomainSnapshot(
        freshness=health_freshness,
        evaluatedAt=NOW,
        backendStatus="ok",
        runtimeHealthy=runtime_healthy,
    )
    mm = MoneyManagementSnapshot(
        capitalAuthority="MONEY_MANAGEMENT",
        capitalSource=CapitalSource.PAPER,
        equity=Decimal("1000.123456789"),
        availableCapital=Decimal("900.123456789"),
        mmMode="MANUAL",
        mmRegime="NORMAL",
        riskBudget=Decimal("10.123456789"),
        remainingExposure=Decimal("75.123456789"),
        remainingPositionCapacity=Decimal("1"),
        ruinGuardStatus="PASS",
        compoundingEnabled=False,
        executionEntryAllowed=True,
        policyVersion="1.0",
        evaluatedAt=NOW,
        authorityFresh=True,
        drawdown=Decimal("1.1"),
        currentExposure=Decimal("24.876543211"),
        openPositionState="NONE",
        freshness=mm_freshness,
    )
    return ReadOnlySupervisorSnapshot(
        capturedAt=NOW,
        overallFreshness=overall,
        bot=bot,
        loop=loop,
        trade=trade,
        governance=governance,
        emergency=emergency,
        execution=execution,
        market=market,
        decision=decision,
        health=health,
        moneyManagement=mm,
        warnings=warnings,
    )


def mm_output(
    *,
    state="NORMAL",
    direction="MAINTAIN",
    multiplier="0.8",
    condition="HEALTHY",
    source_at=NOW,
    assessed_at=MM_NOW,
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
        "reasons": ["MM authority observation"],
        "uncertainties": [],
        "recoveryConditions": [],
        "sourceEvaluatedAt": source_at,
        "assessedAt": assessed_at,
    }


def master_output(
    *,
    posture="NORMAL",
    trading="CONTINUE",
    mm_direction="MAINTAIN",
    mm_multiplier="0.8",
    attention="NOT_REQUIRED",
    summary="現在の重要状態は正常で、追加対応は不要です。",
    source_at=NOW,
    decided_at=MASTER_NOW,
):
    return {
        "schemaVersion": 1,
        "agent": "MASTER_SUPERVISOR",
        "mode": "SHADOW",
        "overallPosture": posture,
        "tradingRecommendation": trading,
        "mmRecommendation": {
            "riskDirection": mm_direction,
            "riskMultiplier": mm_multiplier,
        },
        "humanAttention": attention,
        "summary": summary,
        "reasons": ["検証済みAuthorityに基づく判断"],
        "conflicts": [],
        "uncertainties": [],
        "nextReviewConditions": [],
        "sourceEvaluatedAt": source_at,
        "decidedAt": decided_at,
    }


class FakeProvider:
    def __init__(self, value, *, availability=ProviderAvailability.AVAILABLE, name="fake-provider"):
        self.value = value
        self._availability = availability
        self._identity = ProviderIdentity(name, "1.0")
        self.requests = []

    @property
    def identity(self):
        return self._identity

    @property
    def availability(self):
        return self._availability

    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        self.requests.append((deepcopy(input_data), output_contract, timeout_seconds))
        return ProviderResult(self.value)


class TimeoutProvider(FakeProvider):
    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        raise TimeoutError("traceback SECRET_VALUE_MUST_NOT_LEAK")


class ExceptionProvider(FakeProvider):
    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        raise RuntimeError("traceback SECRET_VALUE_MUST_NOT_LEAK")


def mm_result(source, value=None):
    provider = FakeProvider(value or mm_output(), name="fake-mm-provider")
    return evaluate_mm_shadow(source, provider, MM_NOW)


def evaluate(source=None, mm=None, value=None, provider=None):
    source = source or snapshot()
    mm = mm or mm_result(source)
    provider = provider or FakeProvider(value or master_output(), name="fake-master-provider")
    return evaluate_master_shadow(
        source,
        mm,
        provider,
        MASTER_NOW,
        TRADINGAI_OPERATOR_CONSTITUTION,
    ), provider, mm


def test_valid_normal_decision_is_bound_allowlisted_and_side_effect_free():
    source = snapshot()
    mm = mm_result(source)
    before_snapshot = source.model_dump(mode="python")
    before_mm = mm.model_dump(mode="python")
    result, provider, _ = evaluate(source, mm)

    assert source.model_dump(mode="python") == before_snapshot
    assert mm.model_dump(mode="python") == before_mm
    assert result.status is MasterShadowRuntimeStatus.COMPLETED
    assert result.providerStatus is MasterShadowProviderStatus.VALID
    assert result.validationStatus is MasterShadowValidationStatus.VALID
    assert result.decision.overallPosture.value == "NORMAL"
    assert result.decision.summary == "現在の重要状態は正常で、追加対応は不要です。"
    assert result.mode.value == "SHADOW"
    assert result.operationalEffect == "NONE"
    assert result.configurationChanged is False
    assert result.riskChanged is False
    assert result.quantityChanged is False
    assert result.botStateChanged is False
    assert result.loopStateChanged is False
    assert result.governanceChanged is False
    assert result.orderAction == "NONE"

    request, contract, timeout = provider.requests[0]
    assert request["agentId"] == "MASTER_SUPERVISOR"
    assert request["mode"] == "SHADOW"
    assert request["constitutionIdentity"]["constitutionDigest"] == TRADINGAI_OPERATOR_CONSTITUTION.digest()
    assert request["context"]["availableSpecialists"] == ["MM_SUPERVISOR"]
    assert request["context"]["unavailableSpecialists"] == [
        "STRATEGY_SUPERVISOR", "EXECUTION_SUPERVISOR", "SYSTEM_HEALTH_SUPERVISOR"
    ]
    assert "moneyManagement" not in request["context"]
    assert "raw" not in request["context"]
    assert contract.__name__ == "MasterSupervisorDecision"
    assert timeout == 5.0


@pytest.mark.parametrize(
    "value",
    [
        master_output(
            posture="CAUTION", trading="PAUSE_NEW_ENTRIES", attention="REVIEW",
            summary="現在は慎重な確認が必要です。",
        ),
        master_output(
            posture="DEFENSIVE", trading="PAUSE_NEW_ENTRIES", mm_direction="REDUCE",
            mm_multiplier=None, attention="APPROVAL_REQUIRED",
            summary="現在は防御的な方針と確認が必要です。",
        ),
        master_output(
            posture="UNKNOWN", trading="UNKNOWN", mm_direction="UNKNOWN",
            mm_multiplier=None, attention="REVIEW",
            summary="現在は判断材料の確認が必要です。",
        ),
    ],
)
def test_valid_caution_defensive_unknown_and_human_attention(value):
    result, _, _ = evaluate(value=value)
    assert result.status is MasterShadowRuntimeStatus.COMPLETED
    assert result.decision.humanAttention.value == value["humanAttention"]


def test_valid_continue_reduced_follows_mm_reduce_and_safe_strengthening_is_allowed():
    source = snapshot()
    specialist = mm_result(source, mm_output(
        state="CAUTION", direction="REDUCE", multiplier="0.8", condition="DEGRADED"
    ))
    value = master_output(
        posture="CAUTION",
        trading="CONTINUE_REDUCED",
        mm_direction="REDUCE",
        mm_multiplier="0.8",
        attention="REVIEW",
        summary="現在は縮小提案を伴う慎重な継続判断です。",
    )
    result, _, _ = evaluate(source, specialist, value)
    assert result.status is MasterShadowRuntimeStatus.COMPLETED
    stronger = master_output(
        posture="DEFENSIVE",
        trading="PAUSE_NEW_ENTRIES",
        mm_direction="PAUSE",
        mm_multiplier=None,
        attention="REVIEW",
        summary="現在は新規取引を見合わせる防御判断です。",
    )
    result, _, _ = evaluate(source, specialist, stronger)
    assert result.status is MasterShadowRuntimeStatus.COMPLETED


def test_valid_locked_stop_requires_immediate_attention_but_changes_nothing():
    source = snapshot(governance_enabled=False, emergency_locked=True, emergency_state="LOCKED")
    specialist = mm_result(source, mm_output(
        state="LOCKED", direction="PAUSE", multiplier=None, condition="CRITICAL"
    ))
    value = master_output(
        posture="LOCKED", trading="STOP", mm_direction="PAUSE", mm_multiplier=None,
        attention="IMMEDIATE_ACTION", summary="緊急状態のため直ちに人間の確認が必要です。",
    )
    result, _, _ = evaluate(source, specialist, value)
    assert result.status is MasterShadowRuntimeStatus.COMPLETED
    assert result.decision.tradingRecommendation.value == "STOP"
    assert result.operationalEffect == "NONE"
    assert result.botStateChanged is False


@pytest.mark.parametrize("mode", ["ADVISORY", "ACTIVE"])
def test_master_mode_promotion_is_rejected(mode):
    value = master_output()
    value["mode"] = mode
    result, _, _ = evaluate(value=value)
    assert result.decision is None
    assert result.failureCode is SupervisorFailureCode.MODE_NOT_ALLOWED


def test_growth_is_always_rejected_without_strategy_edge_authorities():
    value = master_output(posture="GROWTH")
    result, _, _ = evaluate(value=value)
    assert result.decision is None
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


@pytest.mark.parametrize(
    "freshness,expected",
    [
        (Freshness.STALE, SupervisorFailureCode.INPUT_STALE),
        (Freshness.MISSING, SupervisorFailureCode.INPUT_MISSING),
        (Freshness.CONFLICTED, SupervisorFailureCode.INPUT_CONFLICTED),
        (Freshness.UNKNOWN, SupervisorFailureCode.INPUT_INVALID),
    ],
)
def test_nonfresh_snapshot_cannot_produce_normal_or_continue(freshness, expected):
    source = snapshot(overall=freshness)
    specialist = mm_result(source, mm_output(
        state="CAUTION", direction="MAINTAIN", condition="DEGRADED"
    ))
    result, _, _ = evaluate(source, specialist)
    assert result.decision is None
    assert result.failureCode is expected


def test_critical_conflict_emergency_and_governance_precedence():
    warning = SnapshotWarning(
        code=SupervisorFailureCode.INPUT_CONFLICTED,
        domain="governance",
        field="mode",
        message="governance conflict",
        sourceEvaluatedAt=NOW,
    )
    conflict_source = snapshot(warnings=(warning,))
    conflict_mm = mm_result(conflict_source, mm_output(
        state="CAUTION", direction="MAINTAIN", condition="DEGRADED"
    ))
    result, _, _ = evaluate(conflict_source, conflict_mm)
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED

    locked = snapshot(governance_enabled=False, emergency_locked=True, emergency_state="LOCKED")
    specialist = mm_result(locked, mm_output(
        state="LOCKED", direction="PAUSE", multiplier=None, condition="CRITICAL"
    ))
    unsafe = master_output(
        posture="NORMAL", trading="CONTINUE", mm_direction="PAUSE", mm_multiplier=None,
        attention="NOT_REQUIRED",
    )
    result, _, _ = evaluate(locked, specialist, unsafe)
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


@pytest.mark.parametrize(
    "mm_direction,master_direction,trading",
    [
        ("MAINTAIN", "INCREASE_WITHIN_POLICY", "CONTINUE"),
        ("REDUCE", "MAINTAIN", "CONTINUE_REDUCED"),
        ("PAUSE", "PAUSE", "CONTINUE"),
    ],
)
def test_master_cannot_reverse_mm_specialist_safety(mm_direction, master_direction, trading):
    source = snapshot()
    specialist = mm_result(source, mm_output(
        state="DEFENSIVE" if mm_direction != "MAINTAIN" else "NORMAL",
        direction=mm_direction,
        multiplier=None if mm_direction == "PAUSE" else "0.8",
        condition="DEGRADED" if mm_direction != "MAINTAIN" else "HEALTHY",
    ))
    value = master_output(
        posture="CAUTION",
        trading=trading,
        mm_direction=master_direction,
        mm_multiplier=None,
        attention="REVIEW",
    )
    result, _, _ = evaluate(source, specialist, value)
    assert result.decision is None
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


def test_master_cannot_invent_a_new_risk_multiplier():
    value = master_output(mm_multiplier="0.9")
    result, _, _ = evaluate(value=value)
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


def test_continue_reduced_requires_mm_specialist_reduce():
    value = master_output(
        posture="CAUTION",
        trading="CONTINUE_REDUCED",
        attention="REVIEW",
        summary="現在は慎重な継続判断です。",
    )
    result, _, _ = evaluate(value=value)
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


@pytest.mark.parametrize(
    "summary",
    [
        "Risk changed by Master Supervisor.",
        "Botを停止しました。",
        "Strategy Edge確認済みです。",
        "Execution Supervisor healthy.",
        "AMS本線統合済みです。",
        "人間の承認を取得しました。",
        "未接続専門Supervisorが正常です。",
        "SHADOW判断を適用済みです。",
    ],
)
def test_forbidden_operational_and_missing_specialist_claims_are_rejected(summary):
    value = master_output(
        posture="CAUTION", trading="PAUSE_NEW_ENTRIES", attention="REVIEW", summary=summary
    )
    result, _, _ = evaluate(value=value)
    assert result.decision is None
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


def test_human_attention_cannot_be_understated():
    value = master_output(
        posture="CAUTION", trading="PAUSE_NEW_ENTRIES", attention="NOT_REQUIRED"
    )
    result, _, _ = evaluate(value=value)
    assert result.failureCode is SupervisorFailureCode.ACTION_PROHIBITED


def test_snapshot_mm_binding_rejects_mismatch_digest_contract_failure_and_null():
    source = snapshot()
    mm = mm_result(source)

    other_snapshot = source.model_copy(update={"capturedAt": NOW - timedelta(seconds=1)})
    result, _, _ = evaluate(other_snapshot, mm)
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED

    bad_audit = mm.auditEvent.model_copy(update={"assessmentDigest": "0" * 64})
    result, _, _ = evaluate(source, mm.model_copy(update={"auditEvent": bad_audit}))
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED

    bad_contract = mm.auditEvent.model_copy(update={"contractVersion": "2"})
    result, _, _ = evaluate(source, mm.model_copy(update={"auditEvent": bad_contract}))
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED

    failed = evaluate_mm_shadow(source, None, MM_NOW)
    result, _, _ = evaluate(source, failed)
    assert result.failureCode is SupervisorFailureCode.INPUT_MISSING

    result, _, _ = evaluate(source, mm.model_copy(update={"assessment": None}))
    assert result.failureCode is SupervisorFailureCode.INPUT_MISSING


def test_binding_rejects_wrong_agent_mode_and_future_assessment():
    source = snapshot()
    mm = mm_result(source)
    wrong_agent = mm.assessment.model_copy(update={"agent": "MASTER_SUPERVISOR"})
    result, _, _ = evaluate(source, mm.model_copy(update={"assessment": wrong_agent}))
    assert result.failureCode is SupervisorFailureCode.MODE_NOT_ALLOWED

    wrong_mode = mm.assessment.model_copy(update={"mode": "ACTIVE"})
    result, _, _ = evaluate(source, mm.model_copy(update={"assessment": wrong_mode}))
    assert result.failureCode is SupervisorFailureCode.MODE_NOT_ALLOWED

    future = mm.assessment.model_copy(update={"assessedAt": MASTER_NOW + timedelta(seconds=1)})
    result, _, _ = evaluate(source, mm.model_copy(update={"assessment": future}))
    assert result.failureCode is SupervisorFailureCode.INPUT_CONFLICTED


def test_provider_unavailable_timeout_exception_and_invalid_output_fail_closed():
    source = snapshot()
    mm = mm_result(source)
    cases = (
        (None, SupervisorFailureCode.PROVIDER_UNAVAILABLE, MasterShadowProviderStatus.UNAVAILABLE),
        (
            FakeProvider(master_output(), availability=ProviderAvailability.UNAVAILABLE),
            SupervisorFailureCode.PROVIDER_UNAVAILABLE,
            MasterShadowProviderStatus.UNAVAILABLE,
        ),
        (TimeoutProvider(master_output()), SupervisorFailureCode.PROVIDER_TIMEOUT, MasterShadowProviderStatus.TIMEOUT),
        (ExceptionProvider(master_output()), SupervisorFailureCode.FAIL_CLOSED, MasterShadowProviderStatus.INVALID),
        (FakeProvider('{"mode":"SHADOW"}'), SupervisorFailureCode.OUTPUT_INVALID, MasterShadowProviderStatus.INVALID),
    )
    for provider, code, status in cases:
        result = evaluate_master_shadow(
            source, mm, provider, MASTER_NOW, TRADINGAI_OPERATOR_CONSTITUTION
        )
        assert result.status is MasterShadowRuntimeStatus.FAILED_CLOSED
        assert result.decision is None
        assert result.failureCode is code
        assert result.providerStatus is status
        assert result.operationalEffect == "NONE"
        assert "SECRET_VALUE_MUST_NOT_LEAK" not in result.stable_json()
        assert "traceback" not in result.stable_json().lower()


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"extra": "rejected"}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"overallPosture": "INVALID"}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"mmRecommendation": {"riskDirection": "MAINTAIN", "riskMultiplier": "NaN"}}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"mmRecommendation": {"riskDirection": "MAINTAIN", "riskMultiplier": "Infinity"}}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"sourceEvaluatedAt": datetime(2026, 8, 12, 12)}, SupervisorFailureCode.OUTPUT_INVALID),
        ({"decidedAt": MASTER_NOW + timedelta(seconds=1)}, SupervisorFailureCode.TIMESTAMP_INVALID),
        ({"agent": "MM_SUPERVISOR"}, SupervisorFailureCode.OUTPUT_INVALID),
    ],
)
def test_invalid_master_contract_output_is_never_adopted(change, expected):
    value = master_output()
    value.update(change)
    result, _, _ = evaluate(value=value)
    assert result.decision is None
    assert result.failureCode is expected
    assert result.validationStatus is MasterShadowValidationStatus.INVALID


def test_same_inputs_and_output_are_deterministic():
    first, _, _ = evaluate()
    second, _, _ = evaluate()
    assert first == second
    assert first.stable_json() == second.stable_json()
    assert first.auditEvent.decisionDigest == second.auditEvent.decisionDigest
