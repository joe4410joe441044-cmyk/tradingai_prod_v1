"""Deterministic, side-effect-free provider used only for boundary tests."""

from dataclasses import dataclass

from pydantic import ValidationError

from backend.ai_advisor.provider_models import (
    PROVIDER_RESPONSE_VERSION,
    AdvisorProviderFinishReason,
    AdvisorProviderRequest,
    AdvisorProviderResponse,
)


@dataclass(frozen=True)
class MockProviderFixture:
    responseText: str
    finishReason: AdvisorProviderFinishReason = AdvisorProviderFinishReason.COMPLETED

    def __post_init__(self):
        if (
            not isinstance(self.responseText, str)
            or not self.responseText
            or len(self.responseText) > 64_000
            or not isinstance(self.finishReason, AdvisorProviderFinishReason)
        ):
            raise ValueError("mock provider fixture validation failed")


@dataclass(frozen=True)
class MockAdvisorProvider:
    fixture: MockProviderFixture

    def generate(
        self,
        request: AdvisorProviderRequest,
    ) -> AdvisorProviderResponse:
        if not isinstance(request, AdvisorProviderRequest):
            raise TypeError("typed AdvisorProviderRequest required")
        try:
            request = AdvisorProviderRequest.model_validate(
                request.model_dump(warnings=False)
            )
            fixture = MockProviderFixture(
                responseText=self.fixture.responseText,
                finishReason=self.fixture.finishReason,
            )
        except (ValidationError, TypeError, ValueError):
            raise ValueError("advisor provider request validation failed") from None
        try:
            return AdvisorProviderResponse(
                providerResponseVersion=PROVIDER_RESPONSE_VERSION,
                providerRequestId=request.providerRequestId,
                requestId=request.requestId,
                promptVersion=request.promptVersion,
                provider=request.provider,
                modelId=request.modelId,
                responseText=fixture.responseText,
                finishReason=fixture.finishReason,
            )
        except ValidationError:
            raise ValueError("advisor provider response validation failed") from None
