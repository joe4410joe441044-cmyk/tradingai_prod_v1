"""Allow-listed system context for the Master Supervisor provider."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from .contracts import (
    CapitalCondition,
    Freshness,
    HumanAttention,
    InputValueState,
    ReadOnlySupervisorSnapshot,
    RiskDirection,
    SnapshotWarning,
    SupervisorContract,
    SupervisorState,
)
from .mm_shadow_runtime import MMShadowRuntimeResult
from .operator_constitution import ConstitutionIdentity, OperatorConstitution, constitution_identity


AVAILABLE_SPECIALISTS = ("MM_SUPERVISOR",)
UNAVAILABLE_SPECIALISTS = (
    "STRATEGY_SUPERVISOR",
    "EXECUTION_SUPERVISOR",
    "SYSTEM_HEALTH_SUPERVISOR",
)


class MasterCriticalFieldState(SupervisorContract):
    domain: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=100)
    state: InputValueState


class MasterShadowContext(SupervisorContract):
    snapshotSchemaVersion: int = Field(ge=1)
    snapshotCapturedAt: datetime
    overallFreshness: Freshness
    governanceFreshness: Freshness
    emergencyFreshness: Freshness
    executionFreshness: Freshness
    healthFreshness: Freshness
    mmFreshness: Freshness
    warnings: tuple[SnapshotWarning, ...] = Field(default=(), max_length=50)
    criticalFieldStates: tuple[MasterCriticalFieldState, ...] = Field(default=(), max_length=100)

    botState: str | None = Field(default=None, max_length=100)
    loopEnabled: bool | None = None
    loopState: str | None = Field(default=None, max_length=100)
    tradeMode: str | None = Field(default=None, max_length=100)
    dryRun: bool | None = None
    autoTradeEnabled: bool | None = None
    realOrderAllowed: bool | None = None

    governanceMode: str | None = Field(default=None, max_length=100)
    governanceExecutionEnabled: bool | None = None
    governanceRiskProfile: str | None = Field(default=None, max_length=100)
    emergencyLocked: bool | None = None
    emergencyState: str | None = Field(default=None, max_length=100)
    executionRuntimeState: str | None = Field(default=None, max_length=100)
    executionSynchronizationState: str | None = Field(default=None, max_length=100)
    pendingOrderState: str | None = Field(default=None, max_length=100)
    backendStatus: str | None = Field(default=None, max_length=100)
    runtimeHealthy: bool | None = None

    activeSymbol: str | None = Field(default=None, max_length=100)
    selectionMode: str | None = Field(default=None, max_length=100)
    selectionSource: str | None = Field(default=None, max_length=100)
    amsRuntimeState: str | None = Field(default=None, max_length=100)
    marketReady: bool | None = None
    marketStale: bool | None = None
    decisionStatus: str | None = Field(default=None, max_length=100)
    decisionEvaluatedAt: datetime | None = None

    mmAssessmentState: SupervisorState
    mmRiskDirection: RiskDirection
    mmRiskMultiplier: Decimal | None = None
    capitalCondition: CapitalCondition
    mmConfidence: float = Field(ge=0.0, le=1.0)
    mmReasons: tuple[str, ...] = Field(default=(), max_length=20)
    mmUncertainties: tuple[str, ...] = Field(default=(), max_length=20)
    mmRecoveryConditions: tuple[str, ...] = Field(default=(), max_length=20)
    mmSourceEvaluatedAt: datetime
    mmRuntimeEvaluatedAt: datetime
    mmAuditEventId: str = Field(min_length=1, max_length=80)
    mmAssessmentDigest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mmAuthorityFresh: bool | None = None
    mmRuinGuardStatus: str | None = Field(default=None, max_length=100)
    mmExecutionEntryAllowed: bool | None = None

    constitutionId: str = Field(min_length=1, max_length=100)
    constitutionVersion: str = Field(min_length=1, max_length=30)
    constitutionDigest: str = Field(pattern=r"^[0-9a-f]{64}$")
    availableSpecialists: Literal[("MM_SUPERVISOR",)] = AVAILABLE_SPECIALISTS
    unavailableSpecialists: Literal[
        ("STRATEGY_SUPERVISOR", "EXECUTION_SUPERVISOR", "SYSTEM_HEALTH_SUPERVISOR")
    ] = UNAVAILABLE_SPECIALISTS


def _critical_field_states(
    snapshot: ReadOnlySupervisorSnapshot,
) -> tuple[MasterCriticalFieldState, ...]:
    values: list[MasterCriticalFieldState] = []
    for domain in ("governance", "emergency", "execution", "health"):
        for observation in getattr(snapshot, domain).fieldStates:
            values.append(MasterCriticalFieldState(
                domain=domain,
                field=observation.field,
                state=observation.state,
            ))
    for observation in snapshot.moneyManagement.fieldStates:
        values.append(MasterCriticalFieldState(
            domain="moneyManagement",
            field=observation.field,
            state=observation.state,
        ))
    return tuple(values)


def build_master_shadow_context(
    snapshot: ReadOnlySupervisorSnapshot,
    mm_runtime_result: MMShadowRuntimeResult,
    constitution: OperatorConstitution,
) -> MasterShadowContext:
    """Build context only after the caller has validated MM identity binding."""
    assessment = mm_runtime_result.assessment
    if assessment is None:
        raise ValueError("validated MM assessment is required")
    identity: ConstitutionIdentity = constitution_identity(constitution)
    audit = mm_runtime_result.auditEvent
    return MasterShadowContext(
        snapshotSchemaVersion=snapshot.schemaVersion,
        snapshotCapturedAt=snapshot.capturedAt,
        overallFreshness=snapshot.overallFreshness,
        governanceFreshness=snapshot.governance.freshness,
        emergencyFreshness=snapshot.emergency.freshness,
        executionFreshness=snapshot.execution.freshness,
        healthFreshness=snapshot.health.freshness,
        mmFreshness=snapshot.moneyManagement.freshness,
        warnings=snapshot.warnings,
        criticalFieldStates=_critical_field_states(snapshot),
        botState=snapshot.bot.status,
        loopEnabled=snapshot.loop.enabled,
        loopState=snapshot.loop.state,
        tradeMode=snapshot.trade.selectedMode,
        dryRun=snapshot.trade.dryRun,
        autoTradeEnabled=snapshot.trade.autoTradeEnabled,
        realOrderAllowed=snapshot.trade.realOrderAllowed,
        governanceMode=snapshot.governance.mode,
        governanceExecutionEnabled=snapshot.governance.executionEnabled,
        governanceRiskProfile=snapshot.governance.riskProfile,
        emergencyLocked=snapshot.emergency.locked,
        emergencyState=snapshot.emergency.state,
        executionRuntimeState=snapshot.execution.authoritativeRuntimeState,
        executionSynchronizationState=snapshot.execution.synchronizationState,
        pendingOrderState=snapshot.execution.pendingOrderState,
        backendStatus=snapshot.health.backendStatus,
        runtimeHealthy=snapshot.health.runtimeHealthy,
        activeSymbol=snapshot.market.activeSymbol,
        selectionMode=snapshot.market.selectionMode,
        selectionSource=snapshot.market.selectionSource,
        amsRuntimeState=snapshot.market.amsRuntimeState,
        marketReady=snapshot.market.marketReady,
        marketStale=snapshot.market.marketStale,
        decisionStatus=snapshot.decision.status,
        decisionEvaluatedAt=snapshot.decision.evaluatedAt,
        mmAssessmentState=assessment.assessmentState,
        mmRiskDirection=assessment.recommendedRiskDirection,
        mmRiskMultiplier=assessment.recommendedRiskMultiplier,
        capitalCondition=assessment.capitalCondition,
        mmConfidence=assessment.confidence,
        mmReasons=assessment.reasons,
        mmUncertainties=assessment.uncertainties,
        mmRecoveryConditions=assessment.recoveryConditions,
        mmSourceEvaluatedAt=assessment.sourceEvaluatedAt,
        mmRuntimeEvaluatedAt=audit.runtimeEvaluatedAt,
        mmAuditEventId=audit.eventId,
        mmAssessmentDigest=audit.assessmentDigest,
        mmAuthorityFresh=snapshot.moneyManagement.authorityFresh,
        mmRuinGuardStatus=snapshot.moneyManagement.ruinGuardStatus,
        mmExecutionEntryAllowed=snapshot.moneyManagement.executionEntryAllowed,
        constitutionId=identity.constitutionId,
        constitutionVersion=identity.constitutionVersion,
        constitutionDigest=identity.constitutionDigest,
    )
