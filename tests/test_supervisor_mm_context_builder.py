from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

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
from backend.supervisor.mm_context_builder import MMShadowContext, build_mm_shadow_context


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def supervisor_snapshot(
    *,
    overall=Freshness.FRESH,
    mm_freshness=Freshness.FRESH,
    authority_fresh=True,
    evaluated_at=NOW,
    ruin_guard="PASS",
    warnings=(),
):
    domain = DomainSnapshot(freshness=Freshness.FRESH, evaluatedAt=NOW)
    mm = MoneyManagementSnapshot(
        capitalAuthority="MONEY_MANAGEMENT",
        capitalSource=CapitalSource.PAPER,
        equity=Decimal("1000.123456789123456789"),
        availableCapital=Decimal("900.123456789123456789"),
        mmMode="MANUAL",
        mmRegime="NORMAL",
        riskBudget=Decimal("10.123456789123456789"),
        remainingExposure=Decimal("75.123456789123456789"),
        remainingPositionCapacity=Decimal("1"),
        ruinGuardStatus=ruin_guard,
        compoundingEnabled=False,
        executionEntryAllowed=False,
        policyVersion="1.0",
        evaluatedAt=evaluated_at,
        authorityFresh=authority_fresh,
        drawdown=Decimal("1.123456789123456789"),
        currentExposure=Decimal("25.123456789123456789"),
        openPositionState="NONE",
        reasonCodes=("WITHIN_POLICY",),
        freshness=mm_freshness,
        fieldStates=(
            FieldValueObservation(field="equity", state=InputValueState.PRESENT),
        ),
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


def test_context_is_exact_allowlist_and_preserves_decimal_and_field_states():
    mm_warning = SnapshotWarning(
        code=SupervisorFailureCode.INPUT_STALE,
        domain="moneyManagement",
        field="authorityFresh",
        message="authority observation is stale",
        sourceEvaluatedAt=NOW,
    )
    bot_warning = SnapshotWarning(
        code=SupervisorFailureCode.INPUT_MISSING,
        domain="bot",
        field="source",
        message="bot is missing",
    )
    snapshot = supervisor_snapshot(warnings=(bot_warning, mm_warning))
    original = snapshot.model_dump(mode="python")
    context = build_mm_shadow_context(snapshot)

    assert snapshot.model_dump(mode="python") == original
    assert set(context.model_dump()) == set(MMShadowContext.model_fields)
    assert context.equity == Decimal("1000.123456789123456789")
    assert context.compoundingEnabled is False
    assert context.fieldStates[0].state is InputValueState.PRESENT
    assert context.warnings == (mm_warning,)
    assert "bot" not in context.stable_json().lower()
    assert "governance" not in context.stable_json().lower()


def test_context_does_not_invent_unowned_metrics_or_missing_values():
    snapshot = supervisor_snapshot()
    mm = snapshot.moneyManagement.model_copy(update={
        "equity": None,
        "riskBudget": None,
        "remainingExposure": None,
        "remainingPositionCapacity": None,
        "openPositionState": "UNKNOWN",
        "ruinGuardStatus": "UNAVAILABLE",
    })
    context = build_mm_shadow_context(snapshot.model_copy(update={"moneyManagement": mm}))

    assert context.equity is None
    assert context.riskBudget is None
    assert context.remainingExposure is None
    assert context.remainingPositionCapacity is None
    assert context.openPositionState == "UNKNOWN"
    assert context.ruinGuardStatus == "UNAVAILABLE"
    serialized = context.stable_json()
    for invented in ("lossStreak", "winRate", "payoffRatio", "credential", "environment"):
        assert invented not in serialized
