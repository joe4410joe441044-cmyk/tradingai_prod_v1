"""Immutable input and result contracts for AI Advisor orchestration."""

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

from backend.ai_advisor.context_builder import (
    SpecificationSourceInput,
    SummarySourceInput,
)
from backend.ai_advisor.conversation_models import (
    AdvisorContractModel,
    AdvisorConversationMessage,
    AdvisorRequest,
)
from backend.ai_advisor.models import AdvisorRuntimeResponse
from backend.ai_advisor.response_models import AdvisorResponseEnvelope


class AdvisorServiceContractModel(AdvisorContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )


class AdvisorServiceStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AdvisorServiceFailureCode(str, Enum):
    ADVISOR_INVALID_CONVERSATION = "ADVISOR_INVALID_CONVERSATION"
    ADVISOR_CONTEXT_INVALID = "ADVISOR_CONTEXT_INVALID"
    ADVISOR_PROMPT_INVALID = "ADVISOR_PROMPT_INVALID"
    ADVISOR_PROVIDER_REQUEST_INVALID = "ADVISOR_PROVIDER_REQUEST_INVALID"
    ADVISOR_PROVIDER_FAILURE = "ADVISOR_PROVIDER_FAILURE"
    ADVISOR_PROVIDER_RESPONSE_INVALID = "ADVISOR_PROVIDER_RESPONSE_INVALID"
    ADVISOR_PARSE_FAILURE = "ADVISOR_PARSE_FAILURE"
    ADVISOR_RESPONSE_INVALID = "ADVISOR_RESPONSE_INVALID"


def service_failure_message(code: AdvisorServiceFailureCode) -> str:
    return {
        AdvisorServiceFailureCode.ADVISOR_INVALID_CONVERSATION: (
            "advisor conversation validation failed"
        ),
        AdvisorServiceFailureCode.ADVISOR_CONTEXT_INVALID: (
            "advisor context validation failed"
        ),
        AdvisorServiceFailureCode.ADVISOR_PROMPT_INVALID: (
            "advisor prompt validation failed"
        ),
        AdvisorServiceFailureCode.ADVISOR_PROVIDER_REQUEST_INVALID: (
            "advisor provider request validation failed"
        ),
        AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE: (
            "advisor provider unavailable"
        ),
        AdvisorServiceFailureCode.ADVISOR_PROVIDER_RESPONSE_INVALID: (
            "advisor provider response validation failed"
        ),
        AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE: (
            "advisor response parsing failed"
        ),
        AdvisorServiceFailureCode.ADVISOR_RESPONSE_INVALID: (
            "advisor response validation failed"
        ),
    }[code]


class AdvisorServiceContextInput(AdvisorServiceContractModel):
    generatedAt: datetime
    runtime: Optional[AdvisorRuntimeResponse] = None
    runtimeSourceId: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ] = "advisor-runtime"
    specifications: Annotated[
        Tuple[SpecificationSourceInput, ...],
        Field(default_factory=tuple, max_length=32, strict=False),
    ]
    marketIntelligenceSources: Annotated[
        Tuple[SummarySourceInput, ...],
        Field(default_factory=tuple, max_length=32, strict=False),
    ]
    moneyManagementSources: Annotated[
        Tuple[SummarySourceInput, ...],
        Field(default_factory=tuple, max_length=32, strict=False),
    ]
    conversationHistory: Annotated[
        Tuple[AdvisorConversationMessage, ...],
        Field(default_factory=tuple, max_length=20, strict=False),
    ]
    currentMessage: Optional[AdvisorConversationMessage] = None

    @field_validator("generatedAt")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generatedAt must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_serializer("generatedAt", when_used="json")
    def serialize_generated_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class AdvisorServiceInput(AdvisorServiceContractModel):
    request: AdvisorRequest
    contextInput: AdvisorServiceContextInput
    providerRequestId: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    receivedAt: datetime

    @field_validator("receivedAt")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receivedAt must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("providerRequestId")
    @classmethod
    def validate_provider_request_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("providerRequestId must contain visible characters")
        return value

    @field_serializer("receivedAt", when_used="json")
    def serialize_received_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class AdvisorServiceFailure(AdvisorServiceContractModel):
    code: AdvisorServiceFailureCode
    safeMessage: Literal[
        "advisor conversation validation failed",
        "advisor context validation failed",
        "advisor prompt validation failed",
        "advisor provider request validation failed",
        "advisor provider unavailable",
        "advisor provider response validation failed",
        "advisor response parsing failed",
        "advisor response validation failed",
    ]
    retryAllowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_message(self) -> "AdvisorServiceFailure":
        if self.safeMessage != service_failure_message(self.code):
            raise ValueError("service failure code and message must match")
        return self


class AdvisorServiceResult(AdvisorServiceContractModel):
    status: AdvisorServiceStatus
    response: Optional[AdvisorResponseEnvelope] = None
    failure: Optional[AdvisorServiceFailure] = None

    @model_validator(mode="after")
    def validate_result(self) -> "AdvisorServiceResult":
        if self.status is AdvisorServiceStatus.SUCCEEDED:
            if self.response is None or self.failure is not None:
                raise ValueError("successful service result requires only response")
        elif self.response is not None or self.failure is None:
            raise ValueError("failed service result requires only failure")
        return self
