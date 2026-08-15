"""Strict, immutable contracts for AI Advisor response validation."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Optional, Tuple

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.ai_advisor.conversation_models import (
    AdvisorContractModel,
    AdvisorFreshnessState,
    AdvisorSourceType,
)

RESPONSE_VERSION = "1.0"
RESPONSE_FORMAT_VERSION = "1.0"
MAX_RAW_RESPONSE_CHARACTERS = 32_000
MAX_SUMMARY_CHARACTERS = 8_000
MAX_STATEMENT_CHARACTERS = 4_000
MAX_FACTS = 32
MAX_INFERENCES = 16
MAX_UNKNOWNS = 16
MAX_RESPONSE_WARNINGS = 32
MAX_RESPONSE_SOURCES = 32
MAX_SERIALIZED_RESPONSE_CHARACTERS = 64_000
REJECTED_SUMMARY = (
    "The advisor response was rejected because it violated the response safety "
    "contract. No action was executed and no system state was changed."
)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Statement = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_STATEMENT_CHARACTERS),
]
Summary = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_SUMMARY_CHARACTERS),
]


class AdvisorResponseContractModel(AdvisorContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )


class AdvisorResponseStatus(str, Enum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    REJECTED = "REJECTED"


class AdvisorUncertainty(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AdvisorUnknownReason(str, Enum):
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_EXPIRED = "SOURCE_EXPIRED"
    SOURCE_UNKNOWN = "SOURCE_UNKNOWN"
    CONTRACT_NOT_DEFINED = "CONTRACT_NOT_DEFINED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class AdvisorResponseWarningCode(str, Enum):
    STALE_SOURCE = "STALE_SOURCE"
    EXPIRED_SOURCE = "EXPIRED_SOURCE"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    MISSING_SOURCE = "MISSING_SOURCE"
    INFERENCE_PRESENT = "INFERENCE_PRESENT"
    SAFETY_LIMITATION = "SAFETY_LIMITATION"
    RESPONSE_SANITIZED = "RESPONSE_SANITIZED"
    SOURCE_REFERENCE_INVALID = "SOURCE_REFERENCE_INVALID"


class AdvisorSafetyDisclosure(str, Enum):
    READ_ONLY = "READ_ONLY"
    NO_ACTION_EXECUTED = "NO_ACTION_EXECUTED"
    NO_STATE_CHANGED = "NO_STATE_CHANGED"
    NO_TOOL_USED = "NO_TOOL_USED"
    USER_REVIEW_REQUIRED = "USER_REVIEW_REQUIRED"


class AdvisorForbiddenClaim(str, Enum):
    SECRET_DISCLOSURE_CLAIM = "SECRET_DISCLOSURE_CLAIM"
    UNGROUNDED_CURRENT_MARKET_CLAIM = "UNGROUNDED_CURRENT_MARKET_CLAIM"
    UNGROUNDED_CURRENT_RUNTIME_CLAIM = "UNGROUNDED_CURRENT_RUNTIME_CLAIM"
    EXECUTION_CLAIM = "EXECUTION_CLAIM"
    ORDER_ACTION_CLAIM = "ORDER_ACTION_CLAIM"
    POSITION_ACTION_CLAIM = "POSITION_ACTION_CLAIM"
    GOVERNANCE_OVERRIDE_CLAIM = "GOVERNANCE_OVERRIDE_CLAIM"
    AUTHORITY_ESCALATION_CLAIM = "AUTHORITY_ESCALATION_CLAIM"
    TOOL_USE_CLAIM = "TOOL_USE_CLAIM"
    FILESYSTEM_ACCESS_CLAIM = "FILESYSTEM_ACCESS_CLAIM"
    NETWORK_ACCESS_CLAIM = "NETWORK_ACCESS_CLAIM"
    BOT_CONTROL_CLAIM = "BOT_CONTROL_CLAIM"
    RESPONSE_CONTRACT_INVALID = "RESPONSE_CONTRACT_INVALID"


class AdvisorRawResponse(AdvisorResponseContractModel):
    requestId: Identifier
    promptVersion: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    responseFormatVersion: Literal["1.0"]
    responseText: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_RAW_RESPONSE_CHARACTERS),
    ]
    receivedAt: datetime

    @field_validator("receivedAt")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receivedAt must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_serializer("receivedAt", when_used="json")
    def serialize_received_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class AdvisorFact(AdvisorResponseContractModel):
    factId: Identifier
    statement: Statement
    sourceIds: Annotated[
        Tuple[Identifier, ...],
        Field(min_length=1, max_length=MAX_RESPONSE_SOURCES, strict=False),
    ]
    freshness: AdvisorFreshnessState


class AdvisorInference(AdvisorResponseContractModel):
    inferenceId: Identifier
    statement: Statement
    basedOnSourceIds: Annotated[
        Tuple[Identifier, ...],
        Field(min_length=1, max_length=MAX_RESPONSE_SOURCES, strict=False),
    ]
    uncertainty: AdvisorUncertainty


class AdvisorUnknown(AdvisorResponseContractModel):
    unknownId: Identifier
    topic: Statement
    reason: AdvisorUnknownReason
    requiredSourceType: Optional[AdvisorSourceType] = None


class AdvisorActionableUnknown(AdvisorResponseContractModel):
    unknownId: Identifier
    subject: Statement
    reason: Statement
    missingInformation: Statement
    safeNextStep: Statement
    decisionImpact: Statement
    operationalEffect: Literal["NONE"] = "NONE"


class AdvisorResponseWarning(AdvisorResponseContractModel):
    code: AdvisorResponseWarningCode
    message: Optional[Statement] = None


class AdvisorFreshnessDisclosure(AdvisorResponseContractModel):
    sourceId: Identifier
    freshness: AdvisorFreshnessState


class AdvisorGroundedClaim(AdvisorResponseContractModel):
    claimId: Identifier
    claimType: Literal["FACT", "INTERPRETATION", "INFERENCE", "UNKNOWN"]
    text: Statement
    citationSourceIds: Tuple[Identifier, ...]
    uncertainty: AdvisorUncertainty
    freshness: AdvisorFreshnessState

    @model_validator(mode="after")
    def validate_grounded_claim(self) -> "AdvisorGroundedClaim":
        if self.claimType != "UNKNOWN" and not self.citationSourceIds:
            raise ValueError("material grounded claim requires citation")
        if self.claimType == "FACT" and self.freshness in {
            AdvisorFreshnessState.STALE,
            AdvisorFreshnessState.UNKNOWN,
            AdvisorFreshnessState.LAST_GOOD,
        }:
            raise ValueError("unsafe freshness cannot be a current FACT")
        return self


class AdvisorCitation(AdvisorResponseContractModel):
    sourceId: Identifier
    sourceType: AdvisorSourceType
    displayTitle: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    claimIds: Tuple[Identifier, ...]
    freshness: AdvisorFreshnessState


class AdvisorResponseCandidate(AdvisorResponseContractModel):
    responseVersion: Literal["1.0"]
    requestId: Identifier
    promptVersion: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    summary: Summary
    facts: Annotated[
        Tuple[AdvisorFact, ...],
        Field(max_length=MAX_FACTS, strict=False),
    ]
    inferences: Annotated[
        Tuple[AdvisorInference, ...],
        Field(max_length=MAX_INFERENCES, strict=False),
    ]
    unknowns: Annotated[
        Tuple[AdvisorUnknown, ...],
        Field(max_length=MAX_UNKNOWNS, strict=False),
    ]
    warnings: Annotated[
        Tuple[AdvisorResponseWarning, ...],
        Field(max_length=MAX_RESPONSE_WARNINGS, strict=False),
    ]
    sourceReferences: Annotated[
        Tuple[Identifier, ...],
        Field(max_length=MAX_RESPONSE_SOURCES, strict=False),
    ]
    freshnessDisclosures: Annotated[
        Tuple[AdvisorFreshnessDisclosure, ...],
        Field(max_length=MAX_RESPONSE_SOURCES, strict=False),
    ]
    safetyDisclosures: Annotated[
        Tuple[AdvisorSafetyDisclosure, ...],
        Field(max_length=5, strict=False),
    ]


class AdvisorResponseEnvelope(AdvisorResponseContractModel):
    responseVersion: Literal["1.0"]
    requestId: Identifier
    promptVersion: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    receivedAt: datetime
    status: AdvisorResponseStatus
    summary: Summary
    facts: Tuple[AdvisorFact, ...]
    inferences: Tuple[AdvisorInference, ...]
    unknowns: Tuple[AdvisorUnknown, ...]
    warnings: Tuple[AdvisorResponseWarning, ...]
    sourceReferences: Tuple[Identifier, ...]
    freshnessDisclosures: Tuple[AdvisorFreshnessDisclosure, ...]
    safetyDisclosures: Tuple[AdvisorSafetyDisclosure, ...]
    forbiddenClaims: Tuple[AdvisorForbiddenClaim, ...]
    validationWarnings: Tuple[AdvisorResponseWarningCode, ...]
    primaryRejectionReason: Optional[AdvisorForbiddenClaim] = None
    responseCategory: Optional[
        Literal[
            "SYSTEM_GUIDANCE",
            "SPECIFICATION_LOOKUP",
            "SAFETY_REFUSAL",
            "INSUFFICIENT_DATA",
        ]
    ] = None
    conclusion: Optional[Summary] = None
    groundedClaims: Tuple[AdvisorGroundedClaim, ...] = ()
    actionableUnknowns: Tuple[AdvisorActionableUnknown, ...] = ()
    citations: Tuple[AdvisorCitation, ...] = ()
    limitations: Tuple[Statement, ...] = ()
    safeAlternative: Optional[Summary] = None
    refusalCategory: Optional[str] = Field(default=None, max_length=64)

    @field_validator("receivedAt")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receivedAt must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_serializer("receivedAt", when_used="json")
    def serialize_received_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_status_invariants(self) -> "AdvisorResponseEnvelope":
        required = {
            AdvisorSafetyDisclosure.READ_ONLY,
            AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
            AdvisorSafetyDisclosure.NO_STATE_CHANGED,
            AdvisorSafetyDisclosure.NO_TOOL_USED,
        }
        if not required <= set(self.safetyDisclosures):
            raise ValueError("required safety disclosures are missing")
        if self.status is AdvisorResponseStatus.REJECTED:
            if (
                self.facts
                or self.inferences
                or self.unknowns
                or self.warnings
                or self.sourceReferences
                or self.freshnessDisclosures
                or self.actionableUnknowns
            ):
                raise ValueError("rejected response cannot retain sourced content")
            if not self.forbiddenClaims or self.primaryRejectionReason is None:
                raise ValueError("rejected response requires a rejection reason")
            if self.primaryRejectionReason not in self.forbiddenClaims:
                raise ValueError("primary rejection reason must be a forbidden claim")
            if self.summary != REJECTED_SUMMARY:
                raise ValueError("rejected response must use the fixed summary")
        else:
            if self.forbiddenClaims or self.primaryRejectionReason is not None:
                raise ValueError("non-rejected response cannot have forbidden claims")
            if self.status is AdvisorResponseStatus.VALID and (
                self.warnings or self.unknowns or self.validationWarnings
            ):
                raise ValueError("valid response cannot contain warnings or unknowns")
            if self.status is AdvisorResponseStatus.VALID_WITH_WARNINGS and not (
                self.warnings
                or self.unknowns
                or self.validationWarnings
                or self.inferences
            ):
                raise ValueError("warning status requires warning content")
            unknown_ids = {item.unknownId for item in self.unknowns}
            actionable_ids = {item.unknownId for item in self.actionableUnknowns}
            if (
                unknown_ids != actionable_ids
                or len(self.actionableUnknowns) != len(actionable_ids)
            ):
                raise ValueError("every unknown requires one actionable explanation")
        claim_ids = [claim.claimId for claim in self.groundedClaims]
        citation_ids = [citation.sourceId for citation in self.citations]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("grounded claim IDs must be unique")
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("citation source IDs must be unique")
        known_claims = set(claim_ids)
        known_sources = set(citation_ids)
        for claim in self.groundedClaims:
            if not set(claim.citationSourceIds) <= known_sources:
                raise ValueError("grounded claim has unknown citation")
        for citation in self.citations:
            if not citation.claimIds or not set(citation.claimIds) <= known_claims:
                raise ValueError("citation has invalid claim mapping")
        if self.responseCategory == "SAFETY_REFUSAL":
            if self.status is not AdvisorResponseStatus.REJECTED:
                raise ValueError("safety refusal must be rejected")
            if self.refusalCategory is None or self.safeAlternative is None:
                raise ValueError("safety refusal requires safe details")
        return self
