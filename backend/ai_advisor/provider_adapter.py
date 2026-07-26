"""Pure provider request construction and provider interface."""

from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from backend.ai_advisor.conversation_models import AdvisorRequest
from backend.ai_advisor.prompt_builder import (
    build_advisor_prompt,
    render_advisor_prompt,
)
from backend.ai_advisor.prompt_models import (
    AdvisorPromptEnvelope,
    AdvisorPromptPolicy,
)
from backend.ai_advisor.provider_models import (
    PROVIDER_REQUEST_VERSION,
    AdvisorDisabledPolicy,
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderConfig,
    AdvisorProviderRequest,
    AdvisorProviderResponse,
)


@runtime_checkable
class AdvisorProvider(Protocol):
    def generate(
        self,
        request: AdvisorProviderRequest,
    ) -> AdvisorProviderResponse:
        """Return one complete, non-streaming provider response."""


def invoke_provider_once(
    *,
    provider: AdvisorProvider,
    request: AdvisorProviderRequest,
) -> AdvisorProviderResponse:
    """Invoke exactly once and reject non-response or streaming-like output."""

    if not isinstance(request, AdvisorProviderRequest):
        raise TypeError("typed AdvisorProviderRequest required")
    try:
        request = AdvisorProviderRequest.model_validate(
            request.model_dump(warnings=False)
        )
        response = provider.generate(request)
    except (ValidationError, ValueError, TypeError):
        raise ValueError("advisor provider unavailable") from None
    if not isinstance(response, AdvisorProviderResponse):
        raise ValueError("advisor provider response validation failed")
    try:
        return AdvisorProviderResponse.model_validate(
            response.model_dump(warnings=False)
        )
    except ValidationError:
        raise ValueError("advisor provider response validation failed") from None


def build_provider_request(
    *,
    request: AdvisorRequest,
    prompt_envelope: AdvisorPromptEnvelope,
    config: AdvisorProviderConfig,
    model_policy: AdvisorModelPolicy,
    capabilities: AdvisorProviderCapabilities,
    provider_request_id: str,
) -> AdvisorProviderRequest:
    """Bind one trusted prompt to a fixed provider request."""

    if not isinstance(request, AdvisorRequest):
        raise TypeError("typed AdvisorRequest required")
    if not isinstance(prompt_envelope, AdvisorPromptEnvelope):
        raise TypeError("typed AdvisorPromptEnvelope required")
    if not isinstance(config, AdvisorProviderConfig):
        raise TypeError("typed AdvisorProviderConfig required")
    if not isinstance(model_policy, AdvisorModelPolicy):
        raise TypeError("typed AdvisorModelPolicy required")
    if not isinstance(capabilities, AdvisorProviderCapabilities):
        raise TypeError("typed AdvisorProviderCapabilities required")
    try:
        request = AdvisorRequest.model_validate(request.model_dump(warnings=False))
        prompt_envelope = AdvisorPromptEnvelope.model_validate(
            prompt_envelope.model_dump(warnings=False)
        )
        config = AdvisorProviderConfig.model_validate(config.model_dump(warnings=False))
        model_policy = AdvisorModelPolicy.model_validate(
            model_policy.model_dump(warnings=False)
        )
        capabilities = AdvisorProviderCapabilities.model_validate(
            capabilities.model_dump(warnings=False)
        )
    except ValidationError:
        raise ValueError("advisor provider request validation failed") from None
    try:
        expected_prompt = build_advisor_prompt(
            request=request,
            context=request.contextEnvelope,
            policy=AdvisorPromptPolicy(),
        )
    except (ValidationError, ValueError, TypeError):
        raise ValueError("advisor provider request validation failed") from None
    if (
        request.requestId != prompt_envelope.requestId
        or prompt_envelope != expected_prompt
        or config.provider is not model_policy.provider
        or config.provider is not capabilities.provider
        or config.modelId not in model_policy.allowedModelIds
        or capabilities.supportsTextGeneration is not True
        or capabilities.supportsStrictJson is not True
        or capabilities.supportsToolCalling is not False
        or capabilities.supportsFunctionCalling is not False
        or capabilities.supportsStreaming is not False
        or capabilities.supportsImages is not False
        or capabilities.supportsFiles is not False
    ):
        raise ValueError("advisor provider request validation failed")
    try:
        return AdvisorProviderRequest(
            providerRequestVersion=PROVIDER_REQUEST_VERSION,
            providerRequestId=provider_request_id,
            requestId=request.requestId,
            promptVersion=prompt_envelope.promptVersion,
            provider=config.provider,
            modelId=config.modelId,
            renderedPrompt=render_advisor_prompt(prompt_envelope),
            responseFormat=config.responseFormat,
            timeoutSeconds=config.timeoutSeconds,
            maxOutputCharacters=config.maxOutputCharacters,
            toolCallingPolicy=AdvisorDisabledPolicy.DISABLED,
            functionCallingPolicy=AdvisorDisabledPolicy.DISABLED,
            streamingPolicy=AdvisorDisabledPolicy.DISABLED,
            retryPolicy=config.retryPolicy,
        )
    except (ValidationError, ValueError):
        raise ValueError("advisor provider request validation failed") from None
