"""Provider-neutral, non-operational Master Supervisor SHADOW runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import re
from typing import Literal, Mapping

from pydantic import BaseModel, Field, ValidationError, model_validator

from .agent_registry import Capability, DataSource
from .contracts import (
    CapitalCondition,
    Freshness,
    HumanAttention,
    MasterSupervisorDecision,
    ReadOnlySupervisorSnapshot,
    RiskDirection,
    SupervisorAgentId,
    SupervisorContract,
    SupervisorMode,
    SupervisorState,
    TradingRecommendation,
)
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from .master_context_builder import MasterShadowContext, build_master_shadow_context
from .master_shadow_audit import MasterShadowAuditEvent, build_master_shadow_audit_event
from .mm_shadow_audit import build_mm_shadow_audit_event
from .mm_shadow_runtime import MMShadowRuntimeResult, MMShadowRuntimeStatus
from .operator_constitution import (
    ConstitutionIdentity,
    OperatorConstitution,
    constitution_identity,
)
from .provider import ProviderAvailability, ProviderResult, StructuredOutputProvider
from .security_boundary import validate_agent_capability, validate_data_source_access
from .validation import validate_master_decision


MASTER_SHADOW_PROVIDER_TIMEOUT_SECONDS = 5.0
MASTER_SHADOW_CONTRACT_VERSION = "1"
MASTER_PROHIBITED_CLAIMS = (
    "RUNTIME_CHANGED",
    "RISK_CHANGED",
    "QUANTITY_CHANGED",
    "MM_CONFIGURATION_CHANGED",
    "BOT_OR_LOOP_CHANGED",
    "ORDER_SUBMITTED",
    "GOVERNANCE_CHANGED",
    "MODE_PROMOTED",
    "AMS_MAINLINE_INTEGRATED",
    "STRATEGY_EDGE_CONFIRMED",
    "UNAVAILABLE_SPECIALIST_HEALTHY",
    "HUMAN_APPROVAL_OBTAINED",
)


class MasterShadowRuntimeStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED_CLOSED = "FAILED_CLOSED"


class MasterShadowProviderStatus(str, Enum):
    VALID = "VALID"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"


class MasterShadowValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_RUN = "NOT_RUN"


class MasterShadowProviderRequest(SupervisorContract):
    schemaVersion: Literal[1] = 1
    agentId: Literal[SupervisorAgentId.MASTER_SUPERVISOR] = SupervisorAgentId.MASTER_SUPERVISOR
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    contractVersion: Literal["1"] = MASTER_SHADOW_CONTRACT_VERSION
    constitutionIdentity: ConstitutionIdentity
    context: MasterShadowContext
    allowedOutputSchema: tuple[str, ...] = Field(min_length=1, max_length=30)
    prohibitedClaims: tuple[str, ...] = Field(min_length=1, max_length=30)
    requestedAt: datetime

    @model_validator(mode="after")
    def bounded_request(self) -> "MasterShadowProviderRequest":
        if self.requestedAt.tzinfo is None or self.requestedAt.utcoffset() is None:
            raise ValueError("request timestamp must be timezone-aware")
        for values in (self.allowedOutputSchema, self.prohibitedClaims):
            if len(values) != len(set(values)) or any(
                not value.strip() or len(value) > 100 for value in values
            ):
                raise ValueError("request entries must be unique and bounded")
        return self


class MasterShadowRuntimeResult(SupervisorContract):
    status: MasterShadowRuntimeStatus
    decision: MasterSupervisorDecision | None
    providerIdentity: str = Field(min_length=1, max_length=100)
    providerVersion: str = Field(min_length=1, max_length=100)
    providerStatus: MasterShadowProviderStatus
    validationStatus: MasterShadowValidationStatus
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    operationalEffect: Literal["NONE"] = "NONE"
    configurationChanged: Literal[False] = False
    riskChanged: Literal[False] = False
    quantityChanged: Literal[False] = False
    botStateChanged: Literal[False] = False
    loopStateChanged: Literal[False] = False
    governanceChanged: Literal[False] = False
    orderAction: Literal["NONE"] = "NONE"
    failureCode: SupervisorFailureCode | None
    auditEvent: MasterShadowAuditEvent

    @model_validator(mode="after")
    def coherent_outcome(self) -> "MasterShadowRuntimeResult":
        if self.status is MasterShadowRuntimeStatus.COMPLETED:
            if (
                self.decision is None
                or self.failureCode is not None
                or self.providerStatus is not MasterShadowProviderStatus.VALID
                or self.validationStatus is not MasterShadowValidationStatus.VALID
            ):
                raise ValueError("completed Master result is incoherent")
        elif self.decision is not None or self.failureCode is None:
            raise ValueError("failed Master result is incoherent")
        return self


def _safe_provider_metadata(
    provider: StructuredOutputProvider | None,
) -> tuple[str, str]:
    if provider is None:
        return "DISABLED", "NONE"
    try:
        values = (provider.identity.name, provider.identity.version)
        suspicious = (
            "SECRET", "TOKEN", "CREDENTIAL", "API_KEY", "APIKEY",
            "PRIVATE_KEY", "ACCESS_KEY",
        )
        if all(
            isinstance(value, str)
            and 1 <= len(value) <= 100
            and re.fullmatch(r"[A-Za-z0-9._-]+", value)
            and not any(marker in value.upper() for marker in suspicious)
            for value in values
        ):
            return values
    except Exception:
        pass
    return "UNAVAILABLE", "UNKNOWN"


def _validate_mm_binding(
    snapshot: ReadOnlySupervisorSnapshot,
    mm_result: MMShadowRuntimeResult,
    evaluated_at: datetime,
) -> None:
    if (
        mm_result.status is not MMShadowRuntimeStatus.COMPLETED
        or mm_result.assessment is None
        or mm_result.failureCode is not None
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_MISSING,
            "completed MM SHADOW assessment is required",
        )
    assessment = mm_result.assessment
    audit = mm_result.auditEvent
    if (
        mm_result.mode is not SupervisorMode.SHADOW
        or assessment.mode is not SupervisorMode.SHADOW
        or assessment.agent is not SupervisorAgentId.MM_SUPERVISOR
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.MODE_NOT_ALLOWED,
            "MM assessment identity or mode is invalid",
        )
    expected_source = snapshot.moneyManagement.evaluatedAt
    if expected_source is None:
        source_matches = (
            audit.sourceEvaluatedAt is None
            and assessment.sourceEvaluatedAt == snapshot.capturedAt
        )
    else:
        source_matches = (
            audit.sourceEvaluatedAt == expected_source
            and assessment.sourceEvaluatedAt == expected_source
        )
    if (
        audit.snapshotCapturedAt != snapshot.capturedAt
        or audit.overallFreshness is not snapshot.overallFreshness
        or not source_matches
        or assessment.assessedAt != audit.runtimeEvaluatedAt
        or audit.runtimeEvaluatedAt > evaluated_at
        or assessment.sourceEvaluatedAt > evaluated_at
        or assessment.assessedAt > evaluated_at
        or audit.providerIdentity != mm_result.providerIdentity
        or audit.providerVersion != mm_result.providerVersion
        or audit.contractVersion != "1"
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_CONFLICTED,
            "MM result does not bind to the supplied snapshot",
        )
    expected_audit = build_mm_shadow_audit_event(
        snapshot_captured_at=audit.snapshotCapturedAt,
        source_evaluated_at=audit.sourceEvaluatedAt,
        runtime_evaluated_at=audit.runtimeEvaluatedAt,
        provider_identity=audit.providerIdentity,
        provider_version=audit.providerVersion,
        status="COMPLETED",
        failure_code=None,
        overall_freshness=audit.overallFreshness,
        assessment=assessment,
    )
    if audit != expected_audit:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_CONFLICTED,
            "MM assessment digest or audit identity is invalid",
        )


def _critical_nonfresh(context: MasterShadowContext) -> bool:
    return any(value is not Freshness.FRESH for value in (
        context.overallFreshness,
        context.governanceFreshness,
        context.emergencyFreshness,
        context.executionFreshness,
        context.healthFreshness,
        context.mmFreshness,
    ))


def _critical_freshness_failure(
    context: MasterShadowContext,
) -> SupervisorFailureCode | None:
    values = (
        context.overallFreshness,
        context.governanceFreshness,
        context.emergencyFreshness,
        context.executionFreshness,
        context.healthFreshness,
        context.mmFreshness,
    )
    if Freshness.CONFLICTED in values:
        return SupervisorFailureCode.INPUT_CONFLICTED
    if Freshness.MISSING in values:
        return SupervisorFailureCode.INPUT_MISSING
    if Freshness.STALE in values:
        return SupervisorFailureCode.INPUT_STALE
    if Freshness.UNKNOWN in values:
        return SupervisorFailureCode.INPUT_INVALID
    return None


def _critical_conflict(context: MasterShadowContext) -> bool:
    return any(
        warning.code is SupervisorFailureCode.INPUT_CONFLICTED
        and warning.domain in {
            "governance", "emergency", "execution", "health", "moneyManagement"
        }
        for warning in context.warnings
    )


def _hard_safety_locked(context: MasterShadowContext) -> bool:
    emergency_state = (context.emergencyState or "UNKNOWN").upper()
    return (
        context.emergencyLocked is True
        or emergency_state in {"LOCKED", "ACTION_REQUIRED", "PROCESSING"}
        or context.governanceExecutionEnabled is False
    )


def _normal_requirements_met(context: MasterShadowContext) -> bool:
    ruin_guard = (context.mmRuinGuardStatus or "UNKNOWN").upper()
    emergency_state = (context.emergencyState or "UNKNOWN").upper()
    backend_status = (context.backendStatus or "UNKNOWN").upper()
    execution_state = (context.executionRuntimeState or "UNKNOWN").upper()
    synchronization = (context.executionSynchronizationState or "UNKNOWN").upper()
    real_order_conflict = context.realOrderAllowed is True and (
        context.governanceExecutionEnabled is not True
        or context.emergencyLocked is not False
        or context.mmExecutionEntryAllowed is not True
    )
    return bool(
        not _critical_nonfresh(context)
        and not _critical_conflict(context)
        and context.governanceExecutionEnabled is True
        and context.emergencyLocked is False
        and emergency_state == "READY"
        and context.runtimeHealthy is True
        and backend_status in {"OK", "HEALTHY"}
        and execution_state not in {"UNKNOWN", "UNAVAILABLE", "STOPPED"}
        and synchronization not in {"UNKNOWN", "UNAVAILABLE", "STALE", "OFFLINE"}
        and context.mmAssessmentState is SupervisorState.NORMAL
        and context.capitalCondition is CapitalCondition.HEALTHY
        and context.mmRiskDirection is RiskDirection.MAINTAIN
        and context.mmAuthorityFresh is True
        and ruin_guard not in {"UNKNOWN", "UNAVAILABLE", "FAIL", "FAILED", "BLOCKED"}
        and not real_order_conflict
    )


_DIRECTION_SAFETY = {
    RiskDirection.INCREASE_WITHIN_POLICY: 0,
    RiskDirection.MAINTAIN: 1,
    RiskDirection.REDUCE: 2,
    RiskDirection.PAUSE: 3,
}


def _validate_mm_consistency(
    decision: MasterSupervisorDecision,
    context: MasterShadowContext,
) -> None:
    specialist = context.mmRiskDirection
    master = decision.mmRecommendation.riskDirection
    if specialist is RiskDirection.UNKNOWN:
        if master not in {RiskDirection.UNKNOWN, RiskDirection.PAUSE}:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.ACTION_PROHIBITED,
                "Master cannot strengthen unknown MM authority",
            )
    elif master is RiskDirection.UNKNOWN:
        pass
    elif _DIRECTION_SAFETY.get(master, -1) < _DIRECTION_SAFETY.get(specialist, 99):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "Master recommendation is riskier than MM specialist",
        )
    multiplier = decision.mmRecommendation.riskMultiplier
    if master is specialist:
        if multiplier not in {None, context.mmRiskMultiplier}:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.ACTION_PROHIBITED,
                "Master invented an MM multiplier",
            )
    elif multiplier is not None:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "strengthened Master recommendation cannot invent a multiplier",
        )
    recommendation = decision.tradingRecommendation
    if specialist is RiskDirection.PAUSE and recommendation in {
        TradingRecommendation.CONTINUE,
        TradingRecommendation.CONTINUE_REDUCED,
    }:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "trading recommendation conflicts with MM pause",
        )
    if specialist is RiskDirection.REDUCE and recommendation is TradingRecommendation.CONTINUE:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "trading recommendation conflicts with MM reduction",
        )
    if (
        recommendation is TradingRecommendation.CONTINUE_REDUCED
        and specialist is not RiskDirection.REDUCE
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "CONTINUE_REDUCED requires an MM specialist reduction",
        )
    if specialist is RiskDirection.UNKNOWN and recommendation in {
        TradingRecommendation.CONTINUE,
        TradingRecommendation.CONTINUE_REDUCED,
    }:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "trading continuation requires known MM authority",
        )


_ATTENTION_LEVEL = {
    HumanAttention.NOT_REQUIRED: 0,
    HumanAttention.REVIEW: 1,
    HumanAttention.APPROVAL_REQUIRED: 2,
    HumanAttention.IMMEDIATE_ACTION: 3,
}


_FORBIDDEN_CLAIMS = (
    "RISK CHANGED", "CHANGED RISK", "RISK MODIFIED", "RISK ADJUSTED",
    "LOT CHANGED", "QUANTITY CHANGED", "BOT STOPPED", "STOPPED THE BOT",
    "ORDER SUBMITTED", "ORDER PLACED", "GOVERNANCE CHANGED",
    "PROMOTED TO ACTIVE", "MODE IS ACTIVE", "AMS MAINLINE INTEGRATED",
    "SAFE SWITCH SUCCEEDED", "MICRO EDGE SUITABILITY PASSED",
    "STRATEGY EDGE CONFIRMED", "STRATEGY EDGE VERIFIED",
    "STRATEGY SUPERVISOR HEALTHY", "EXECUTION SUPERVISOR HEALTHY",
    "SYSTEM HEALTH SUPERVISOR HEALTHY", "HUMAN APPROVAL OBTAINED",
    "リスクを変更しました", "LOTを変更しました", "数量を変更しました",
    "RISKを変更しました", "RISKを調整しました",
    "BOTを停止しました", "注文を出しました", "GOVERNANCEを変更しました",
    "ACTIVEへ移行しました", "AMS本線統合済み", "STRATEGY EDGE確認済み",
    "STRATEGY SUPERVISORは正常", "EXECUTION SUPERVISORは正常",
    "SYSTEM HEALTH SUPERVISORは正常", "未接続専門SUPERVISORが正常",
    "SHADOW判断を適用済み", "SHADOW DECISION APPLIED",
    "人間の承認を取得しました", "承認済みです",
)


def _validate_claims(decision: MasterSupervisorDecision) -> None:
    text = " ".join((
        decision.summary,
        *decision.reasons,
        *decision.conflicts,
        *decision.uncertainties,
        *decision.nextReviewConditions,
    )).upper().replace("_", " ")
    if any(pattern.upper() in text for pattern in _FORBIDDEN_CLAIMS):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "Master output contains a prohibited claim",
        )
    reason_codes = re.findall(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", decision.summary)
    numeric_tokens = re.findall(r"\d+(?:\.\d+)?", decision.summary)
    if len(reason_codes) > 1 or len(numeric_tokens) > 6:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.OUTPUT_INVALID,
            "Master summary is not suitable for the normal display",
        )


def _validate_master_safety(
    decision: MasterSupervisorDecision,
    context: MasterShadowContext,
    snapshot: ReadOnlySupervisorSnapshot,
    evaluated_at: datetime,
) -> None:
    validate_master_decision(decision, snapshot, now=evaluated_at)
    if decision.sourceEvaluatedAt != context.snapshotCapturedAt or decision.decidedAt != evaluated_at:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.TIMESTAMP_INVALID,
            "Master decision timestamps do not match the bounded request",
        )
    if decision.overallPosture is SupervisorState.GROWTH:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "GROWTH requires unavailable specialist authorities",
        )
    locked = _hard_safety_locked(context)
    conflict = _critical_conflict(context)
    freshness_failure = _critical_freshness_failure(context)
    nonfresh = freshness_failure is not None
    if locked and (
        decision.overallPosture is not SupervisorState.LOCKED
        or decision.tradingRecommendation is not TradingRecommendation.STOP
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "Governance or Emergency stop must take precedence",
        )
    if decision.overallPosture is SupervisorState.NORMAL and not _normal_requirements_met(context):
        code = (
            SupervisorFailureCode.INPUT_CONFLICTED if conflict
            else freshness_failure if freshness_failure is not None
            else SupervisorFailureCode.ACTION_PROHIBITED
        )
        raise SupervisorBoundaryError(code, "NORMAL requirements are not satisfied")
    if (conflict or nonfresh) and decision.tradingRecommendation in {
        TradingRecommendation.CONTINUE,
        TradingRecommendation.CONTINUE_REDUCED,
    }:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_CONFLICTED if conflict else freshness_failure,
            "critical uncertainty forbids trading continuation",
        )
    if decision.tradingRecommendation is TradingRecommendation.CONTINUE and not _normal_requirements_met(context):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "CONTINUE requires fully validated normal authority",
        )
    required_attention = HumanAttention.NOT_REQUIRED
    if locked or conflict or decision.overallPosture is SupervisorState.LOCKED:
        required_attention = HumanAttention.IMMEDIATE_ACTION
    elif (
        nonfresh
        or decision.overallPosture in {
            SupervisorState.CAUTION,
            SupervisorState.DEFENSIVE,
            SupervisorState.UNKNOWN,
        }
        or context.mmUncertainties
        or context.mmRecoveryConditions
        or decision.conflicts
        or decision.uncertainties
    ):
        required_attention = HumanAttention.REVIEW
    if _ATTENTION_LEVEL[decision.humanAttention] < _ATTENTION_LEVEL[required_attention]:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "human attention is understated",
        )
    if decision.humanAttention is HumanAttention.NOT_REQUIRED and (
        decision.overallPosture is not SupervisorState.NORMAL
        or not _normal_requirements_met(context)
    ):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "NOT_REQUIRED is limited to fully validated NORMAL state",
        )
    _validate_mm_consistency(decision, context)
    _validate_claims(decision)


def _failure_result(
    *,
    snapshot: ReadOnlySupervisorSnapshot,
    mm_digest: str,
    identity: ConstitutionIdentity,
    evaluated_at: datetime,
    provider_identity: str,
    provider_version: str,
    provider_status: MasterShadowProviderStatus,
    validation_status: MasterShadowValidationStatus,
    failure_code: SupervisorFailureCode,
) -> MasterShadowRuntimeResult:
    audit = build_master_shadow_audit_event(
        snapshot_captured_at=snapshot.capturedAt,
        mm_assessment_digest=mm_digest,
        constitution_identity=identity,
        runtime_evaluated_at=evaluated_at,
        provider_identity=provider_identity,
        provider_version=provider_version,
        status="FAILED_CLOSED",
        failure_code=failure_code,
        overall_freshness=snapshot.overallFreshness,
        decision=None,
    )
    return MasterShadowRuntimeResult(
        status=MasterShadowRuntimeStatus.FAILED_CLOSED,
        decision=None,
        providerIdentity=provider_identity,
        providerVersion=provider_version,
        providerStatus=provider_status,
        validationStatus=validation_status,
        failureCode=failure_code,
        auditEvent=audit,
    )


def evaluate_master_shadow(
    snapshot: ReadOnlySupervisorSnapshot,
    mm_runtime_result: MMShadowRuntimeResult,
    provider: StructuredOutputProvider | None,
    evaluated_at: datetime,
    constitution: OperatorConstitution,
    *,
    timeout_seconds: float = MASTER_SHADOW_PROVIDER_TIMEOUT_SECONDS,
) -> MasterShadowRuntimeResult:
    """Generate an explanatory SHADOW decision without operational authority."""
    identity = constitution_identity(constitution)
    mm_digest = mm_runtime_result.auditEvent.assessmentDigest
    provider_identity, provider_version = _safe_provider_metadata(provider)
    if (
        not isinstance(evaluated_at, datetime)
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        return _failure_result(
            snapshot=snapshot,
            mm_digest=mm_digest,
            identity=identity,
            evaluated_at=snapshot.capturedAt,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=MasterShadowProviderStatus.INVALID,
            validation_status=MasterShadowValidationStatus.INVALID,
            failure_code=SupervisorFailureCode.TIMESTAMP_INVALID,
        )
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    try:
        validate_agent_capability(
            SupervisorAgentId.MASTER_SUPERVISOR,
            Capability.PRODUCE_SHADOW_DECISION,
            SupervisorMode.SHADOW,
        )
        validate_data_source_access(
            SupervisorAgentId.MASTER_SUPERVISOR,
            DataSource.SUPERVISOR_SNAPSHOT,
        )
        validate_data_source_access(
            SupervisorAgentId.MASTER_SUPERVISOR,
            DataSource.MM_SUPERVISOR_ASSESSMENT,
        )
        _validate_mm_binding(snapshot, mm_runtime_result, evaluated_at)
        context = build_master_shadow_context(snapshot, mm_runtime_result, constitution)
        if provider is None or provider.availability is not ProviderAvailability.AVAILABLE:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.PROVIDER_UNAVAILABLE,
                "Master provider is unavailable",
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise SupervisorBoundaryError(
                SupervisorFailureCode.INPUT_INVALID,
                "provider timeout must be positive",
            )
        request = MasterShadowProviderRequest(
            constitutionIdentity=identity,
            context=context,
            allowedOutputSchema=tuple(MasterSupervisorDecision.model_fields),
            prohibitedClaims=MASTER_PROHIBITED_CLAIMS,
            requestedAt=evaluated_at,
        )
        provider_input = json.loads(request.stable_json())
        result = provider.generate_structured_output(
            provider_input,
            MasterSupervisorDecision,
            float(timeout_seconds),
        )
        if not isinstance(result, ProviderResult):
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider returned an invalid result envelope",
            )
        if result.failureCode is not None:
            if result.failureCode in {
                SupervisorFailureCode.PROVIDER_TIMEOUT,
                SupervisorFailureCode.PROVIDER_UNAVAILABLE,
            }:
                raise SupervisorBoundaryError(result.failureCode, "provider generation failed")
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider rejected structured generation",
            )
        raw_output = result.output
        if isinstance(raw_output, BaseModel):
            raw_output = raw_output.model_dump(mode="python")
        if not isinstance(raw_output, Mapping):
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider output is not structured",
            )
        if raw_output.get("mode") != SupervisorMode.SHADOW.value:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.MODE_NOT_ALLOWED,
                "provider attempted mode promotion",
            )
        if raw_output.get("agent") != SupervisorAgentId.MASTER_SUPERVISOR.value:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider output has the wrong agent identity",
            )
        try:
            decision = MasterSupervisorDecision.model_validate(dict(raw_output))
        except ValidationError as exc:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider output failed Master contract validation",
            ) from exc
        _validate_master_safety(decision, context, snapshot, evaluated_at)
    except TimeoutError:
        return _failure_result(
            snapshot=snapshot,
            mm_digest=mm_digest,
            identity=identity,
            evaluated_at=evaluated_at,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=MasterShadowProviderStatus.TIMEOUT,
            validation_status=MasterShadowValidationStatus.NOT_RUN,
            failure_code=SupervisorFailureCode.PROVIDER_TIMEOUT,
        )
    except SupervisorBoundaryError as exc:
        if exc.code is SupervisorFailureCode.PROVIDER_UNAVAILABLE:
            provider_status = MasterShadowProviderStatus.UNAVAILABLE
            validation_status = MasterShadowValidationStatus.NOT_RUN
        elif exc.code is SupervisorFailureCode.PROVIDER_TIMEOUT:
            provider_status = MasterShadowProviderStatus.TIMEOUT
            validation_status = MasterShadowValidationStatus.NOT_RUN
        else:
            provider_status = MasterShadowProviderStatus.INVALID
            validation_status = MasterShadowValidationStatus.INVALID
        return _failure_result(
            snapshot=snapshot,
            mm_digest=mm_digest,
            identity=identity,
            evaluated_at=evaluated_at,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=provider_status,
            validation_status=validation_status,
            failure_code=exc.code,
        )
    except Exception:
        return _failure_result(
            snapshot=snapshot,
            mm_digest=mm_digest,
            identity=identity,
            evaluated_at=evaluated_at,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=MasterShadowProviderStatus.INVALID,
            validation_status=MasterShadowValidationStatus.INVALID,
            failure_code=SupervisorFailureCode.FAIL_CLOSED,
        )

    audit = build_master_shadow_audit_event(
        snapshot_captured_at=snapshot.capturedAt,
        mm_assessment_digest=mm_digest,
        constitution_identity=identity,
        runtime_evaluated_at=evaluated_at,
        provider_identity=provider_identity,
        provider_version=provider_version,
        status="COMPLETED",
        failure_code=None,
        overall_freshness=snapshot.overallFreshness,
        decision=decision,
    )
    return MasterShadowRuntimeResult(
        status=MasterShadowRuntimeStatus.COMPLETED,
        decision=decision,
        providerIdentity=provider_identity,
        providerVersion=provider_version,
        providerStatus=MasterShadowProviderStatus.VALID,
        validationStatus=MasterShadowValidationStatus.VALID,
        failureCode=None,
        auditEvent=audit,
    )
