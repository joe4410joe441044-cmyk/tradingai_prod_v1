"""Bounded, content-free observations for semantic response rejections."""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

from pydantic import ConfigDict, field_validator, model_validator

from backend.ai_advisor.provider_models import AdvisorProviderContractModel
from backend.ai_advisor.response_models import (
    AdvisorForbiddenClaim,
    AdvisorResponseEnvelope,
    AdvisorResponseIntegrityDiagnostic,
    AdvisorResponseIntegrityField,
    AdvisorResponseIntegrityViolationCode,
    AdvisorResponseStatus,
)
from backend.ai_advisor.usage_observation import safe_metadata_identifier


class ResponseSafetyRejectionRule(str, Enum):
    SECRET_DISCLOSURE_PATTERN = "SECRET_DISCLOSURE_PATTERN"
    UNGROUNDED_CURRENT_MARKET_PATTERN = "UNGROUNDED_CURRENT_MARKET_PATTERN"
    UNGROUNDED_CURRENT_RUNTIME_PATTERN = "UNGROUNDED_CURRENT_RUNTIME_PATTERN"
    EXECUTION_COMPLETION_PATTERN = "EXECUTION_COMPLETION_PATTERN"
    ORDER_ACTION_PATTERN = "ORDER_ACTION_PATTERN"
    POSITION_ACTION_PATTERN = "POSITION_ACTION_PATTERN"
    GOVERNANCE_OVERRIDE_PATTERN = "GOVERNANCE_OVERRIDE_PATTERN"
    AUTHORITY_ESCALATION_PATTERN = "AUTHORITY_ESCALATION_PATTERN"
    TOOL_USE_PATTERN = "TOOL_USE_PATTERN"
    FILESYSTEM_ACCESS_PATTERN = "FILESYSTEM_ACCESS_PATTERN"
    NETWORK_ACCESS_PATTERN = "NETWORK_ACCESS_PATTERN"
    BOT_CONTROL_PATTERN = "BOT_CONTROL_PATTERN"
    RESPONSE_CONTRACT_INTEGRITY = "RESPONSE_CONTRACT_INTEGRITY"


class ResponseSafetyViolationCategory(str, Enum):
    SECRET = "SECRET"
    OPERATIONAL_ACTION = "OPERATIONAL_ACTION"
    EXTERNAL_ACCESS = "EXTERNAL_ACCESS"
    RESPONSE_CONTRACT_OR_GROUNDING = "RESPONSE_CONTRACT_OR_GROUNDING"


class OperationalIntentClassification(str, Enum):
    ACTION_OR_EXECUTION = "ACTION_OR_EXECUTION"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class ResponseGroundingClassification(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNGROUNDED_CURRENT_CLAIM = "UNGROUNDED_CURRENT_CLAIM"
    UNKNOWN = "UNKNOWN"


_RULE_BY_CLAIM = {
    AdvisorForbiddenClaim.SECRET_DISCLOSURE_CLAIM: (
        ResponseSafetyRejectionRule.SECRET_DISCLOSURE_PATTERN,
        ResponseSafetyViolationCategory.SECRET,
        OperationalIntentClassification.NOT_APPLICABLE,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.UNGROUNDED_CURRENT_MARKET_CLAIM: (
        ResponseSafetyRejectionRule.UNGROUNDED_CURRENT_MARKET_PATTERN,
        ResponseSafetyViolationCategory.RESPONSE_CONTRACT_OR_GROUNDING,
        OperationalIntentClassification.NOT_APPLICABLE,
        ResponseGroundingClassification.UNGROUNDED_CURRENT_CLAIM,
    ),
    AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM: (
        ResponseSafetyRejectionRule.UNGROUNDED_CURRENT_RUNTIME_PATTERN,
        ResponseSafetyViolationCategory.RESPONSE_CONTRACT_OR_GROUNDING,
        OperationalIntentClassification.NOT_APPLICABLE,
        ResponseGroundingClassification.UNGROUNDED_CURRENT_CLAIM,
    ),
    AdvisorForbiddenClaim.EXECUTION_CLAIM: (
        ResponseSafetyRejectionRule.EXECUTION_COMPLETION_PATTERN,
        ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.ORDER_ACTION_CLAIM: (
        ResponseSafetyRejectionRule.ORDER_ACTION_PATTERN,
        ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.POSITION_ACTION_CLAIM: (
        ResponseSafetyRejectionRule.POSITION_ACTION_PATTERN,
        ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.GOVERNANCE_OVERRIDE_CLAIM: (
        ResponseSafetyRejectionRule.GOVERNANCE_OVERRIDE_PATTERN,
        ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.AUTHORITY_ESCALATION_CLAIM: (
        ResponseSafetyRejectionRule.AUTHORITY_ESCALATION_PATTERN,
        ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.TOOL_USE_CLAIM: (
        ResponseSafetyRejectionRule.TOOL_USE_PATTERN,
        ResponseSafetyViolationCategory.EXTERNAL_ACCESS,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.FILESYSTEM_ACCESS_CLAIM: (
        ResponseSafetyRejectionRule.FILESYSTEM_ACCESS_PATTERN,
        ResponseSafetyViolationCategory.EXTERNAL_ACCESS,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.NETWORK_ACCESS_CLAIM: (
        ResponseSafetyRejectionRule.NETWORK_ACCESS_PATTERN,
        ResponseSafetyViolationCategory.EXTERNAL_ACCESS,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.BOT_CONTROL_CLAIM: (
        ResponseSafetyRejectionRule.BOT_CONTROL_PATTERN,
        ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        OperationalIntentClassification.ACTION_OR_EXECUTION,
        ResponseGroundingClassification.NOT_APPLICABLE,
    ),
    AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID: (
        ResponseSafetyRejectionRule.RESPONSE_CONTRACT_INTEGRITY,
        ResponseSafetyViolationCategory.RESPONSE_CONTRACT_OR_GROUNDING,
        OperationalIntentClassification.UNKNOWN,
        ResponseGroundingClassification.UNKNOWN,
    ),
}


class ResponseSafetyRejectionObservation(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    requestId: str
    providerRequestId: str
    rejectionCode: AdvisorForbiddenClaim
    rejectionRule: ResponseSafetyRejectionRule
    failureStage: Literal["RESPONSE_SAFETY_VALIDATION"] = (
        "RESPONSE_SAFETY_VALIDATION"
    )
    violationCategory: ResponseSafetyViolationCategory
    operationalIntent: OperationalIntentClassification
    groundingClassification: ResponseGroundingClassification
    integrityViolationCode: AdvisorResponseIntegrityViolationCode | None = None
    integrityField: AdvisorResponseIntegrityField | None = None
    integrityStage: Literal["POST_PARSE_RESPONSE_INTEGRITY"] | None = None

    @model_validator(mode="after")
    def validate_integrity_fields(self):
        presence = (
            self.integrityViolationCode is not None,
            self.integrityField is not None,
            self.integrityStage is not None,
        )
        if any(presence) and not all(presence):
            raise ValueError("integrity diagnostic fields must be all present or absent")
        return self

    @field_validator("requestId", "providerRequestId")
    @classmethod
    def validate_safe_identifier(cls, value: str) -> str:
        return safe_metadata_identifier(value)


class ResponseSafetyRejectionObservationSink(Protocol):
    def observe(self, observation: ResponseSafetyRejectionObservation) -> None: ...


@dataclass(frozen=True)
class NoOpResponseSafetyRejectionObservationSink:
    def observe(self, observation: ResponseSafetyRejectionObservation) -> None:
        return None


@dataclass
class RecordingResponseSafetyRejectionObservationSink:
    records: list[ResponseSafetyRejectionObservation] = field(default_factory=list)

    def observe(self, observation: ResponseSafetyRejectionObservation) -> None:
        self.records.append(
            ResponseSafetyRejectionObservation.model_validate(
                observation.model_dump(warnings=False)
            )
        )


@dataclass(frozen=True)
class StructuredLoggingResponseSafetyRejectionObservationSink:
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("TradingAI.AIAdvisor")
    )

    def observe(self, observation: ResponseSafetyRejectionObservation) -> None:
        trusted = ResponseSafetyRejectionObservation.model_validate(
            observation.model_dump(warnings=False)
        )
        self.logger.warning(
            "ai_advisor_response_safety_rejection %s",
            json.dumps(
                trusted.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


def project_response_safety_rejection(
    response: AdvisorResponseEnvelope,
    *,
    provider_request_id: str,
    integrity_diagnostic: AdvisorResponseIntegrityDiagnostic | None = None,
) -> ResponseSafetyRejectionObservation:
    trusted = AdvisorResponseEnvelope.model_validate(
        response.model_dump(warnings=False)
    )
    if (
        trusted.status is not AdvisorResponseStatus.REJECTED
        or trusted.primaryRejectionReason is None
    ):
        raise ValueError("rejected advisor response required")
    rule, category, intent, grounding = _RULE_BY_CLAIM[
        trusted.primaryRejectionReason
    ]
    if integrity_diagnostic is not None:
        integrity_diagnostic = AdvisorResponseIntegrityDiagnostic.model_validate(
            integrity_diagnostic.model_dump(warnings=False)
        )
    return ResponseSafetyRejectionObservation(
        requestId=trusted.requestId,
        providerRequestId=provider_request_id,
        rejectionCode=trusted.primaryRejectionReason,
        rejectionRule=rule,
        violationCategory=category,
        operationalIntent=intent,
        groundingClassification=grounding,
        integrityViolationCode=(
            integrity_diagnostic.violationCode if integrity_diagnostic else None
        ),
        integrityField=integrity_diagnostic.field if integrity_diagnostic else None,
        integrityStage=integrity_diagnostic.stage if integrity_diagnostic else None,
    )
