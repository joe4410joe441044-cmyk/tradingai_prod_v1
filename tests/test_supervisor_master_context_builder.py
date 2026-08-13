from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from backend.supervisor.contracts import (
    CapitalSource,
    DomainSnapshot,
    FieldValueObservation,
    Freshness,
    InputValueState,
    MMSupervisorAssessment,
    MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot,
    SnapshotWarning,
)
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.master_context_builder import (
    MasterShadowContext,
    build_master_shadow_context,
)
from backend.supervisor.mm_shadow_audit import build_mm_shadow_audit_event
from backend.supervisor.mm_shadow_runtime import (
    MMShadowProviderStatus,
    MMShadowRuntimeResult,
    MMShadowRuntimeStatus,
    MMShadowValidationStatus,
)
from backend.supervisor.operator_constitution import TRADINGAI_OPERATOR_CONSTITUTION


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def inputs():
    observation = FieldValueObservation(
        field="state", state=InputValueState.PRESENT
    )
    bot = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        status="RUNNING",
        fieldStates=(observation,),
    )
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
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        mode="PAPER",
        executionEnabled=True,
        riskProfile="SAFE",
        fieldStates=(observation,),
    )
    emergency = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        locked=False,
        state="READY",
        fieldStates=(observation,),
    )
    execution = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        authoritativeRuntimeState="SYNCHRONIZED",
        synchronizationState="HEALTHY",
        pendingOrderState="NONE",
        fieldStates=(observation,),
    )
    market = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        activeSymbol="BTC-USDT",
        selectionMode="AUTO",
        selectionSource=None,
        amsRuntimeState=None,
        marketReady=True,
        marketStale=False,
    )
    decision = DomainSnapshot(
        freshness=Freshness.FRESH, evaluatedAt=NOW, status="HOLD"
    )
    health = DomainSnapshot(
        freshness=Freshness.FRESH,
        evaluatedAt=NOW,
        backendStatus="ok",
        runtimeHealthy=True,
        fieldStates=(observation,),
    )
    money_management = MoneyManagementSnapshot(
        capitalAuthority="MONEY_MANAGEMENT",
        capitalSource=CapitalSource.PAPER,
        equity=Decimal("1000.123456789123456789"),
        availableCapital=Decimal("900.123456789123456789"),
        riskBudget=Decimal("10.123456789123456789"),
        remainingExposure=Decimal("75.123456789123456789"),
        remainingPositionCapacity=Decimal("1"),
        ruinGuardStatus="PASS",
        executionEntryAllowed=True,
        evaluatedAt=NOW,
        authorityFresh=True,
        freshness=Freshness.FRESH,
        fieldStates=(observation,),
    )
    warning = SnapshotWarning(
        code=SupervisorFailureCode.INPUT_STALE,
        domain="market",
        field="selectionSource",
        message="selection source is not observed",
        sourceEvaluatedAt=NOW,
    )
    snapshot = ReadOnlySupervisorSnapshot(
        capturedAt=NOW,
        overallFreshness=Freshness.FRESH,
        bot=bot,
        loop=loop,
        trade=trade,
        governance=governance,
        emergency=emergency,
        execution=execution,
        market=market,
        decision=decision,
        health=health,
        moneyManagement=money_management,
        warnings=(warning,),
    )
    assessment = MMSupervisorAssessment(
        assessmentState="NORMAL",
        recommendedRiskDirection="MAINTAIN",
        recommendedRiskMultiplier="0.8",
        capitalCondition="HEALTHY",
        confidence=0.8,
        reasons=("MM authority observation",),
        sourceEvaluatedAt=NOW,
        assessedAt=NOW,
    )
    audit = build_mm_shadow_audit_event(
        snapshot_captured_at=NOW,
        source_evaluated_at=NOW,
        runtime_evaluated_at=NOW,
        provider_identity="fake-mm-provider",
        provider_version="1.0",
        status="COMPLETED",
        failure_code=None,
        overall_freshness=Freshness.FRESH,
        assessment=assessment,
    )
    result = MMShadowRuntimeResult(
        status=MMShadowRuntimeStatus.COMPLETED,
        assessment=assessment,
        providerIdentity="fake-mm-provider",
        providerVersion="1.0",
        providerStatus=MMShadowProviderStatus.VALID,
        validationStatus=MMShadowValidationStatus.VALID,
        failureCode=None,
        auditEvent=audit,
    )
    return snapshot, result


def test_master_context_is_flat_allowlisted_exact_and_non_mutating():
    snapshot, mm_result = inputs()
    before_snapshot = deepcopy(snapshot.model_dump(mode="python"))
    before_mm = deepcopy(mm_result.model_dump(mode="python"))
    context = build_master_shadow_context(
        snapshot, mm_result, TRADINGAI_OPERATOR_CONSTITUTION
    )

    assert snapshot.model_dump(mode="python") == before_snapshot
    assert mm_result.model_dump(mode="python") == before_mm
    assert set(context.model_dump()) == set(MasterShadowContext.model_fields)
    assert context.botState == "RUNNING"
    assert context.governanceExecutionEnabled is True
    assert context.mmRiskMultiplier == Decimal("0.8")
    assert context.mmAssessmentDigest == mm_result.auditEvent.assessmentDigest
    assert context.constitutionDigest == TRADINGAI_OPERATOR_CONSTITUTION.digest()
    assert context.availableSpecialists == ("MM_SUPERVISOR",)
    assert context.unavailableSpecialists == (
        "STRATEGY_SUPERVISOR", "EXECUTION_SUPERVISOR", "SYSTEM_HEALTH_SUPERVISOR"
    )
    assert {item.domain for item in context.criticalFieldStates} == {
        "governance", "emergency", "execution", "health", "moneyManagement"
    }


def test_context_does_not_invent_ams_or_unavailable_specialist_state():
    snapshot, mm_result = inputs()
    context = build_master_shadow_context(
        snapshot, mm_result, TRADINGAI_OPERATOR_CONSTITUTION
    )
    assert context.selectionMode == "AUTO"
    assert context.selectionSource is None
    assert context.amsRuntimeState is None
    serialized = context.stable_json()
    for forbidden in (
        "rawSnapshot", "rawOutput", "apiKey", "credential", "environment",
        "strategySupervisorState", "executionSupervisorState", "systemHealthSupervisorState",
        "safeSwitchSucceeded", "microEdgeSuitabilityPassed",
    ):
        assert forbidden not in serialized
