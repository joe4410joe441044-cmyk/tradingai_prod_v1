"""Strict HTTP boundary contracts for the AI Advisor endpoint."""

from typing import Literal, Optional

from pydantic import Field, model_validator

from backend.ai_advisor.provider_models import AdvisorProviderContractModel
from backend.ai_advisor.response_models import AdvisorResponseEnvelope
from backend.ai_advisor.service_models import (
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceStatus,
)

MAX_ADVISOR_REQUEST_BYTES = 65_536


class AdvisorAPIConfig(AdvisorProviderContractModel):
    enabled: bool = False
    maxRequestBytes: int = Field(default=MAX_ADVISOR_REQUEST_BYTES, ge=1024, le=65_536)
    rateLimitRequests: int = Field(default=10, ge=1, le=100)
    rateLimitWindowSeconds: float = Field(default=60.0, gt=0, le=3600)
    concurrencyLimit: int = Field(default=2, ge=1, le=16)
    concurrencyAcquireTimeoutSeconds: float = Field(default=0.01, ge=0, le=1)
    endpointTimeoutSeconds: float = Field(default=35.0, gt=0, le=120)


class AdvisorAPIPrincipal(AdvisorProviderContractModel):
    principalId: str = Field(min_length=1, max_length=128)
    authenticated: Literal[True]
    advisorAccessAllowed: bool


class AdvisorHTTPRequest(AdvisorProviderContractModel):
    serviceInput: AdvisorServiceInput


class AdvisorHTTPResponse(AdvisorProviderContractModel):
    status: AdvisorServiceStatus
    advisorResponse: Optional[AdvisorResponseEnvelope] = None
    failureCode: Optional[AdvisorServiceFailureCode] = None
    safeMessage: Optional[str] = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_result(self) -> "AdvisorHTTPResponse":
        if self.status is AdvisorServiceStatus.SUCCEEDED:
            if (
                self.advisorResponse is None
                or self.failureCode is not None
                or self.safeMessage is not None
            ):
                raise ValueError("successful HTTP result invariant failed")
        elif (
            self.advisorResponse is not None
            or self.failureCode is None
            or self.safeMessage is None
        ):
            raise ValueError("failed HTTP result invariant failed")
        return self


class AdvisorHTTPError(AdvisorProviderContractModel):
    errorCode: Literal[
        "AUTHENTICATION_REQUIRED",
        "AUTHORIZATION_DENIED",
        "ENDPOINT_DISABLED",
        "UNSUPPORTED_MEDIA_TYPE",
        "REQUEST_TOO_LARGE",
        "REQUEST_INVALID",
        "RATE_LIMIT_EXCEEDED",
        "CONCURRENCY_LIMIT_EXCEEDED",
        "ENDPOINT_TIMEOUT",
        "ADVISOR_UNAVAILABLE",
        "INTERNAL_ERROR",
        "MEMORY_PERSISTENCE_ERROR",
        "MEMORY_DISABLED",
        "CONVERSATION_NOT_FOUND",
    ]
    safeMessage: str = Field(min_length=1, max_length=128)
    retryable: bool
