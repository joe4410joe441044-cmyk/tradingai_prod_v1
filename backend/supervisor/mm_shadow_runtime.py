"""Provider-neutral, non-operational MM Supervisor SHADOW evaluation runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import re
from typing import Literal, Mapping

from pydantic import BaseModel, Field, ValidationError, model_validator

from .contracts import (
    CapitalCondition,
    CapitalSource,
    Freshness,
    MMSupervisorAssessment,
    ReadOnlySupervisorSnapshot,
    RiskDirection,
    SupervisorAgentId,
    SupervisorContract,
    SupervisorMode,
    SupervisorState,
)
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from .mm_context_builder import MMShadowContext, build_mm_shadow_context
from .mm_shadow_audit import MMShadowAuditEvent, build_mm_shadow_audit_event
from .provider import ProviderAvailability, ProviderResult, StructuredOutputProvider
from .security_boundary import validate_agent_capability, validate_data_source_access
from .agent_registry import Capability, DataSource
from .validation import validate_mm_assessment


MM_SHADOW_PROVIDER_TIMEOUT_SECONDS = 45.0
MM_SHADOW_CONTRACT_VERSION = "1"
PROHIBITED_CLAIMS = (
    "RISK_CHANGED",
    "QUANTITY_CHANGED",
    "MM_CONFIGURATION_CHANGED",
    "ORDER_SUBMITTED",
    "GOVERNANCE_CHANGED",
    "EMERGENCY_UNLOCKED",
    "MODE_PROMOTED",
    "UNOBSERVED_AUTHORITY_CONFIRMED",
    "UNAVAILABLE_RUIN_GUARD_PASSED",
)


class MMShadowRuntimeStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED_CLOSED = "FAILED_CLOSED"


class MMShadowProviderStatus(str, Enum):
    VALID = "VALID"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"


class MMShadowValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_RUN = "NOT_RUN"


class MMShadowProviderRequest(SupervisorContract):
    schemaVersion: Literal[1] = 1
    agentId: Literal[SupervisorAgentId.MM_SUPERVISOR] = SupervisorAgentId.MM_SUPERVISOR
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    contractVersion: Literal["1"] = MM_SHADOW_CONTRACT_VERSION
    context: MMShadowContext
    allowedOutputSchema: tuple[str, ...] = Field(min_length=1, max_length=30)
    prohibitedClaims: tuple[str, ...] = Field(min_length=1, max_length=30)
    requestedAt: datetime

    @model_validator(mode="after")
    def bounded_deterministic_request(self) -> "MMShadowProviderRequest":
        if self.requestedAt.tzinfo is None or self.requestedAt.utcoffset() is None:
            raise ValueError("provider request timestamp must be timezone-aware")
        for values in (self.allowedOutputSchema, self.prohibitedClaims):
            if len(values) != len(set(values)) or any(
                not value.strip() or len(value) > 100 for value in values
            ):
                raise ValueError("provider request entries must be unique and bounded")
        return self


class MMShadowRuntimeResult(SupervisorContract):
    status: MMShadowRuntimeStatus
    assessment: MMSupervisorAssessment | None
    providerIdentity: str = Field(min_length=1, max_length=100)
    providerVersion: str = Field(min_length=1, max_length=100)
    providerStatus: MMShadowProviderStatus
    validationStatus: MMShadowValidationStatus
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    operationalEffect: Literal["NONE"] = "NONE"
    configurationChanged: Literal[False] = False
    riskChanged: Literal[False] = False
    quantityChanged: Literal[False] = False
    orderAction: Literal["NONE"] = "NONE"
    failureCode: SupervisorFailureCode | None
    auditEvent: MMShadowAuditEvent

    @model_validator(mode="after")
    def coherent_outcome(self) -> "MMShadowRuntimeResult":
        if self.status is MMShadowRuntimeStatus.COMPLETED:
            if (
                self.assessment is None
                or self.failureCode is not None
                or self.providerStatus is not MMShadowProviderStatus.VALID
                or self.validationStatus is not MMShadowValidationStatus.VALID
            ):
                raise ValueError("completed MM SHADOW result is incoherent")
        elif self.assessment is not None or self.failureCode is None:
            raise ValueError("failed-closed MM SHADOW result is incoherent")
        return self


def _safe_provider_metadata(
    provider: StructuredOutputProvider | None,
) -> tuple[str, str]:
    if provider is None:
        return "DISABLED", "NONE"
    try:
        identity = provider.identity
        values = (identity.name, identity.version)
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


def _freshness_failure(value: Freshness) -> SupervisorFailureCode:
    return {
        Freshness.STALE: SupervisorFailureCode.INPUT_STALE,
        Freshness.MISSING: SupervisorFailureCode.INPUT_MISSING,
        Freshness.CONFLICTED: SupervisorFailureCode.INPUT_CONFLICTED,
        Freshness.UNKNOWN: SupervisorFailureCode.INPUT_INVALID,
    }.get(value, SupervisorFailureCode.FAIL_CLOSED)


def _critical_context_failure(context: MMShadowContext) -> SupervisorFailureCode | None:
    if context.overallFreshness is not Freshness.FRESH:
        return _freshness_failure(context.overallFreshness)
    if context.mmFreshness is not Freshness.FRESH:
        return _freshness_failure(context.mmFreshness)
    if any(
        warning.code is SupervisorFailureCode.INPUT_CONFLICTED
        for warning in context.warnings
    ):
        return SupervisorFailureCode.INPUT_CONFLICTED
    if context.authorityFresh is not True or context.mmEvaluatedAt is None:
        return SupervisorFailureCode.INPUT_MISSING
    if context.capitalSource is CapitalSource.UNKNOWN:
        return SupervisorFailureCode.INPUT_MISSING
    required = (
        context.capitalAuthority,
        context.equity,
        context.availableCapital,
        context.mmRegime,
        context.riskBudget,
        context.remainingExposure,
        context.remainingPositionCapacity,
        context.ruinGuardStatus,
    )
    if any(value is None for value in required) or any(
        isinstance(value, str) and not value.strip() for value in required
    ):
        return SupervisorFailureCode.INPUT_MISSING
    numeric_required = (
        context.equity,
        context.availableCapital,
        context.riskBudget,
        context.remainingExposure,
        context.remainingPositionCapacity,
    )
    if any(value is not None and value < 0 for value in numeric_required):
        return SupervisorFailureCode.INPUT_INVALID
    if isinstance(context.mmRegime, str) and context.mmRegime.upper() == "UNKNOWN":
        return SupervisorFailureCode.INPUT_INVALID
    if (
        isinstance(context.ruinGuardStatus, str)
        and context.ruinGuardStatus.upper() in {"UNKNOWN", "UNAVAILABLE"}
    ):
        return SupervisorFailureCode.INPUT_MISSING
    return None


_FORBIDDEN_TEXT_PATTERNS = (
    "RISK CHANGED",
    "CHANGED RISK",
    "CHANGED THE RISK",
    "RISK MODIFIED",
    "MODIFIED RISK",
    "RISK ADJUSTED",
    "ADJUSTED RISK",
    "QUANTITY CHANGED",
    "CHANGED QUANTITY",
    "LOT CHANGED",
    "CHANGED LOT",
    "MM CONFIGURATION CHANGED",
    "MM SETTINGS CHANGED",
    "MM CONFIGURATION UPDATED",
    "ORDER SUBMITTED",
    "SUBMITTED ORDER",
    "ORDER PLACED",
    "PLACED ORDER",
    "GOVERNANCE CHANGED",
    "CHANGED GOVERNANCE",
    "EMERGENCY UNLOCKED",
    "PROMOTED TO ACTIVE",
    "MODE IS ACTIVE",
)


def _contains_forbidden_claim(
    assessment: MMSupervisorAssessment,
    context: MMShadowContext,
) -> bool:
    text = " ".join(
        assessment.reasons + assessment.uncertainties + assessment.recoveryConditions
    ).upper().replace("_", " ")
    if any(pattern in text for pattern in _FORBIDDEN_TEXT_PATTERNS):
        return True
    if context.authorityFresh is not True and any(
        marker in text for marker in ("AUTHORITY CONFIRMED", "AUTHORITY VERIFIED")
    ):
        return True
    if (
        context.ruinGuardStatus is None
        or context.ruinGuardStatus.upper() in {"UNKNOWN", "UNAVAILABLE"}
    ) and any(marker in text for marker in ("RUIN GUARD PASS", "RUINGUARD PASS")):
        return True
    return False


def _validate_runtime_safety(
    assessment: MMSupervisorAssessment,
    context: MMShadowContext,
    evaluated_at: datetime,
    *,
    critical_conflict_present: bool,
) -> None:
    validate_mm_assessment(assessment, context.mmFreshness, now=evaluated_at)
    expected_source = context.mmEvaluatedAt or context.snapshotCapturedAt
    if assessment.sourceEvaluatedAt != expected_source or assessment.assessedAt != evaluated_at:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.TIMESTAMP_INVALID,
            "provider timestamps do not match the bounded request",
        )
    critical_failure = _critical_context_failure(context)
    if critical_conflict_present:
        critical_failure = SupervisorFailureCode.INPUT_CONFLICTED
    proposes_increase = (
        assessment.recommendedRiskDirection is RiskDirection.INCREASE_WITHIN_POLICY
        or (
            assessment.recommendedRiskMultiplier is not None
            and assessment.recommendedRiskMultiplier > Decimal("1")
        )
    )
    optimistic = (
        assessment.assessmentState in {SupervisorState.NORMAL, SupervisorState.GROWTH}
        or assessment.capitalCondition is CapitalCondition.HEALTHY
    )
    if critical_failure is not None and (proposes_increase or optimistic):
        raise SupervisorBoundaryError(
            critical_failure,
            "unsafe MM assessment requires complete fresh authority",
        )
    # No risk-increase ceiling is present in the snapshot contract. An increase
    # therefore cannot be validated even when every observed input is fresh.
    if proposes_increase:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "risk increase has no authoritative policy ceiling",
        )
    if _contains_forbidden_claim(assessment, context):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED,
            "provider output contains a prohibited operational claim",
        )


def _failure_result(
    *,
    context: MMShadowContext,
    evaluated_at: datetime,
    provider_identity: str,
    provider_version: str,
    provider_status: MMShadowProviderStatus,
    validation_status: MMShadowValidationStatus,
    failure_code: SupervisorFailureCode,
) -> MMShadowRuntimeResult:
    audit = build_mm_shadow_audit_event(
        snapshot_captured_at=context.snapshotCapturedAt,
        source_evaluated_at=context.mmEvaluatedAt,
        runtime_evaluated_at=evaluated_at,
        provider_identity=provider_identity,
        provider_version=provider_version,
        status="FAILED_CLOSED",
        failure_code=failure_code,
        overall_freshness=context.overallFreshness,
        assessment=None,
    )
    return MMShadowRuntimeResult(
        status=MMShadowRuntimeStatus.FAILED_CLOSED,
        assessment=None,
        providerIdentity=provider_identity,
        providerVersion=provider_version,
        providerStatus=provider_status,
        validationStatus=validation_status,
        failureCode=failure_code,
        auditEvent=audit,
    )


def evaluate_mm_shadow(
    snapshot: ReadOnlySupervisorSnapshot,
    provider: StructuredOutputProvider | None,
    evaluated_at: datetime,
    *,
    timeout_seconds: float = MM_SHADOW_PROVIDER_TIMEOUT_SECONDS,
) -> MMShadowRuntimeResult:
    """Evaluate a snapshot without exposing or acquiring operational capability."""
    context = build_mm_shadow_context(snapshot)
    provider_identity, provider_version = _safe_provider_metadata(provider)
    if (
        not isinstance(evaluated_at, datetime)
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        return _failure_result(
            context=context,
            evaluated_at=context.snapshotCapturedAt,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=MMShadowProviderStatus.INVALID,
            validation_status=MMShadowValidationStatus.INVALID,
            failure_code=SupervisorFailureCode.TIMESTAMP_INVALID,
        )
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    try:
        validate_agent_capability(
            SupervisorAgentId.MM_SUPERVISOR,
            Capability.PRODUCE_SHADOW_ASSESSMENT,
            SupervisorMode.SHADOW,
        )
        validate_data_source_access(
            SupervisorAgentId.MM_SUPERVISOR,
            DataSource.MONEY_MANAGEMENT_SNAPSHOT,
        )
        if provider is None or provider.availability is not ProviderAvailability.AVAILABLE:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.PROVIDER_UNAVAILABLE,
                "MM SHADOW provider is unavailable",
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
        request = MMShadowProviderRequest(
            context=context,
            allowedOutputSchema=tuple(MMSupervisorAssessment.model_fields),
            prohibitedClaims=PROHIBITED_CLAIMS,
            requestedAt=evaluated_at,
        )
        provider_input = json.loads(request.stable_json())
        result = provider.generate_structured_output(
            provider_input,
            MMSupervisorAssessment,
            float(timeout_seconds),
        )
        if not isinstance(result, ProviderResult):
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider returned an invalid result envelope",
            )
        if result.failureCode is not None:
            if result.failureCode is SupervisorFailureCode.PROVIDER_TIMEOUT:
                raise SupervisorBoundaryError(result.failureCode, "provider timed out")
            if result.failureCode is SupervisorFailureCode.PROVIDER_UNAVAILABLE:
                raise SupervisorBoundaryError(result.failureCode, "provider unavailable")
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
                "provider output is not a structured mapping",
            )
        if raw_output.get("mode", SupervisorMode.SHADOW) != SupervisorMode.SHADOW.value:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.MODE_NOT_ALLOWED,
                "provider attempted mode promotion",
            )
        try:
            assessment = MMSupervisorAssessment.model_validate(dict(raw_output))
        except ValidationError as exc:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.OUTPUT_INVALID,
                "provider output failed MM assessment validation",
            ) from exc
        critical_conflict_present = any(
            warning.code is SupervisorFailureCode.INPUT_CONFLICTED
            and warning.domain in {"governance", "emergency", "moneyManagement", "health"}
            for warning in snapshot.warnings
        )
        _validate_runtime_safety(
            assessment,
            context,
            evaluated_at,
            critical_conflict_present=critical_conflict_present,
        )
    except TimeoutError:
        return _failure_result(
            context=context,
            evaluated_at=evaluated_at,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=MMShadowProviderStatus.TIMEOUT,
            validation_status=MMShadowValidationStatus.NOT_RUN,
            failure_code=SupervisorFailureCode.PROVIDER_TIMEOUT,
        )
    except SupervisorBoundaryError as exc:
        if exc.code is SupervisorFailureCode.PROVIDER_UNAVAILABLE:
            provider_status = MMShadowProviderStatus.UNAVAILABLE
            validation_status = MMShadowValidationStatus.NOT_RUN
        elif exc.code is SupervisorFailureCode.PROVIDER_TIMEOUT:
            provider_status = MMShadowProviderStatus.TIMEOUT
            validation_status = MMShadowValidationStatus.NOT_RUN
        else:
            provider_status = MMShadowProviderStatus.INVALID
            validation_status = MMShadowValidationStatus.INVALID
        return _failure_result(
            context=context,
            evaluated_at=evaluated_at,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=provider_status,
            validation_status=validation_status,
            failure_code=exc.code,
        )
    except Exception:
        return _failure_result(
            context=context,
            evaluated_at=evaluated_at,
            provider_identity=provider_identity,
            provider_version=provider_version,
            provider_status=MMShadowProviderStatus.INVALID,
            validation_status=MMShadowValidationStatus.INVALID,
            failure_code=SupervisorFailureCode.FAIL_CLOSED,
        )

    audit = build_mm_shadow_audit_event(
        snapshot_captured_at=context.snapshotCapturedAt,
        source_evaluated_at=context.mmEvaluatedAt,
        runtime_evaluated_at=evaluated_at,
        provider_identity=provider_identity,
        provider_version=provider_version,
        status="COMPLETED",
        failure_code=None,
        overall_freshness=context.overallFreshness,
        assessment=assessment,
    )
    return MMShadowRuntimeResult(
        status=MMShadowRuntimeStatus.COMPLETED,
        assessment=assessment,
        providerIdentity=provider_identity,
        providerVersion=provider_version,
        providerStatus=MMShadowProviderStatus.VALID,
        validationStatus=MMShadowValidationStatus.VALID,
        failureCode=None,
        auditEvent=audit,
    )
