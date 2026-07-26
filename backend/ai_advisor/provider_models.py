"""Strict contracts for the network-free AI Advisor provider boundary."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Tuple

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.ai_advisor.conversation_models import AdvisorContractModel

PROVIDER_REQUEST_VERSION = "ai-advisor-provider-request/v1"
PROVIDER_RESPONSE_VERSION = "ai-advisor-provider-response/v1"
PROVIDER_CONFIG_VERSION = "ai-advisor-provider-config/v1"
MOCK_MODEL_ID = "mock-advisor-v1"
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 120
MAX_PROVIDER_OUTPUT_CHARACTERS = 32_000
MAX_PROVIDER_RESPONSE_CHARACTERS = 64_000

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
ModelIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class AdvisorProviderContractModel(AdvisorContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )


class AdvisorProviderCode(str, Enum):
    MOCK = "MOCK"
    OPENAI = "OPENAI"


class AdvisorProviderResponseFormat(str, Enum):
    STRICT_JSON = "STRICT_JSON"


class AdvisorDisabledPolicy(str, Enum):
    DISABLED = "DISABLED"


class AdvisorRetryPolicy(str, Enum):
    NO_RETRY = "NO_RETRY"


class AdvisorProviderFinishReason(str, Enum):
    COMPLETED = "COMPLETED"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    CONTENT_FILTERED = "CONTENT_FILTERED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class AdvisorProviderErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    TIMEOUT = "TIMEOUT"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    CONTENT_FILTERED = "CONTENT_FILTERED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MALFORMED_PROVIDER_RESPONSE = "MALFORMED_PROVIDER_RESPONSE"
    IDENTIFIER_MISMATCH = "IDENTIFIER_MISMATCH"


def provider_safe_message(code: AdvisorProviderErrorCode) -> str:
    if code in {
        AdvisorProviderErrorCode.INVALID_REQUEST,
        AdvisorProviderErrorCode.CAPABILITY_MISMATCH,
        AdvisorProviderErrorCode.UNSUPPORTED_PROVIDER,
        AdvisorProviderErrorCode.UNSUPPORTED_MODEL,
    }:
        return "advisor provider request validation failed"
    if code is AdvisorProviderErrorCode.OUTPUT_TOO_LARGE:
        return "advisor provider output too large"
    if code is AdvisorProviderErrorCode.INCOMPLETE_RESPONSE:
        return "advisor provider response incomplete"
    if code is AdvisorProviderErrorCode.CONTENT_FILTERED:
        return "advisor provider content filtered"
    if code in {
        AdvisorProviderErrorCode.PROVIDER_UNAVAILABLE,
        AdvisorProviderErrorCode.TIMEOUT,
    }:
        return "advisor provider unavailable"
    return "advisor provider response validation failed"


class AdvisorModelPolicy(AdvisorProviderContractModel):
    provider: AdvisorProviderCode
    allowedModelIds: Annotated[
        Tuple[ModelIdentifier, ...],
        Field(min_length=1, max_length=16, strict=False),
    ]
    defaultModelId: ModelIdentifier

    @model_validator(mode="after")
    def validate_allowlist(self) -> "AdvisorModelPolicy":
        if len(set(self.allowedModelIds)) != len(self.allowedModelIds):
            raise ValueError("allowed model IDs must be unique")
        if self.defaultModelId not in self.allowedModelIds:
            raise ValueError("default model must be allowlisted")
        if self.provider is AdvisorProviderCode.MOCK and (
            self.allowedModelIds != (MOCK_MODEL_ID,)
            or self.defaultModelId != MOCK_MODEL_ID
        ):
            raise ValueError("mock provider model policy is fixed")
        return self


class AdvisorProviderCapabilities(AdvisorProviderContractModel):
    provider: AdvisorProviderCode
    supportsTextGeneration: Literal[True]
    supportsStrictJson: Literal[True]
    supportsToolCalling: Literal[False]
    supportsFunctionCalling: Literal[False]
    supportsStreaming: Literal[False]
    supportsImages: Literal[False]
    supportsFiles: Literal[False]


class AdvisorProviderConfig(AdvisorProviderContractModel):
    configVersion: Literal["ai-advisor-provider-config/v1"]
    provider: AdvisorProviderCode
    modelId: ModelIdentifier
    timeoutSeconds: Annotated[
        int,
        Field(ge=MIN_TIMEOUT_SECONDS, le=MAX_TIMEOUT_SECONDS),
    ]
    maxOutputCharacters: Annotated[
        int,
        Field(ge=1, le=MAX_PROVIDER_OUTPUT_CHARACTERS),
    ]
    retryPolicy: Literal[AdvisorRetryPolicy.NO_RETRY]
    responseFormat: Literal[AdvisorProviderResponseFormat.STRICT_JSON]

    @model_validator(mode="after")
    def validate_provider_model(self) -> "AdvisorProviderConfig":
        if self.provider is AdvisorProviderCode.MOCK and self.modelId != MOCK_MODEL_ID:
            raise ValueError("mock provider model is fixed")
        return self


class AdvisorProviderRequest(AdvisorProviderContractModel):
    providerRequestVersion: Literal["ai-advisor-provider-request/v1"]
    providerRequestId: Identifier
    requestId: Identifier
    promptVersion: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    provider: AdvisorProviderCode
    modelId: ModelIdentifier
    renderedPrompt: Annotated[
        str,
        StringConstraints(min_length=1, max_length=64_000),
    ]
    responseFormat: Literal[AdvisorProviderResponseFormat.STRICT_JSON]
    timeoutSeconds: Annotated[
        int,
        Field(ge=MIN_TIMEOUT_SECONDS, le=MAX_TIMEOUT_SECONDS),
    ]
    maxOutputCharacters: Annotated[
        int,
        Field(ge=1, le=MAX_PROVIDER_OUTPUT_CHARACTERS),
    ]
    toolCallingPolicy: Literal[AdvisorDisabledPolicy.DISABLED]
    functionCallingPolicy: Literal[AdvisorDisabledPolicy.DISABLED]
    streamingPolicy: Literal[AdvisorDisabledPolicy.DISABLED]
    retryPolicy: Literal[AdvisorRetryPolicy.NO_RETRY]

    @field_validator("providerRequestId")
    @classmethod
    def validate_provider_request_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("providerRequestId must contain visible characters")
        return value


class AdvisorProviderResponse(AdvisorProviderContractModel):
    providerResponseVersion: Literal["ai-advisor-provider-response/v1"]
    providerRequestId: Identifier
    requestId: Identifier
    promptVersion: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    provider: AdvisorProviderCode
    modelId: ModelIdentifier
    responseText: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_PROVIDER_RESPONSE_CHARACTERS),
    ]
    finishReason: AdvisorProviderFinishReason

    @field_validator("providerRequestId")
    @classmethod
    def validate_provider_request_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("providerRequestId must contain visible characters")
        return value


class AdvisorProviderFailure(AdvisorProviderContractModel):
    errorCode: AdvisorProviderErrorCode
    safeMessage: Literal[
        "advisor provider request validation failed",
        "advisor provider response validation failed",
        "advisor provider unavailable",
        "advisor provider response incomplete",
        "advisor provider content filtered",
        "advisor provider output too large",
    ]
    retryAllowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_safe_message(self) -> "AdvisorProviderFailure":
        if self.safeMessage != provider_safe_message(self.errorCode):
            raise ValueError("provider error code and safe message must match")
        return self


class AdvisorProviderReceivedAt(AdvisorProviderContractModel):
    value: datetime

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received time must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_serializer("value", when_used="json")
    def serialize_value(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
