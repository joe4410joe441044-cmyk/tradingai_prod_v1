"""Pure validation and conversion of provider responses."""

from typing import Union

from pydantic import ValidationError

from backend.ai_advisor.provider_models import (
    MAX_PROVIDER_OUTPUT_CHARACTERS,
    AdvisorProviderCapabilities,
    AdvisorProviderErrorCode,
    AdvisorProviderFailure,
    AdvisorProviderFinishReason,
    AdvisorProviderReceivedAt,
    AdvisorProviderRequest,
    AdvisorProviderResponse,
    provider_safe_message,
)
from backend.ai_advisor.response_models import AdvisorRawResponse

ProviderValidationResult = Union[AdvisorRawResponse, AdvisorProviderFailure]
_NON_CONTENT = frozenset({"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"})


def _has_visible_content(value: str) -> bool:
    return bool(
        "".join(
            character for character in value if character not in _NON_CONTENT
        ).strip()
    )


def _failure(code: AdvisorProviderErrorCode) -> AdvisorProviderFailure:
    return AdvisorProviderFailure(
        errorCode=code,
        safeMessage=provider_safe_message(code),
        retryAllowed=False,
    )


def validate_provider_response(
    *,
    request: AdvisorProviderRequest,
    response: AdvisorProviderResponse,
    capabilities: AdvisorProviderCapabilities,
    received_at: AdvisorProviderReceivedAt,
) -> ProviderValidationResult:
    """Return raw response only after complete provider metadata validation."""

    if not isinstance(request, AdvisorProviderRequest):
        raise TypeError("typed AdvisorProviderRequest required")
    if not isinstance(response, AdvisorProviderResponse):
        raise TypeError("typed AdvisorProviderResponse required")
    if not isinstance(capabilities, AdvisorProviderCapabilities):
        raise TypeError("typed AdvisorProviderCapabilities required")
    if not isinstance(received_at, AdvisorProviderReceivedAt):
        raise TypeError("typed AdvisorProviderReceivedAt required")
    try:
        request = AdvisorProviderRequest.model_validate(
            request.model_dump(warnings=False)
        )
        response = AdvisorProviderResponse.model_validate(
            response.model_dump(warnings=False)
        )
        capabilities = AdvisorProviderCapabilities.model_validate(
            capabilities.model_dump(warnings=False)
        )
        received_at = AdvisorProviderReceivedAt.model_validate(
            received_at.model_dump(warnings=False)
        )
    except ValidationError:
        raise ValueError("advisor provider response validation failed") from None
    if response.modelId != request.modelId:
        return _failure(AdvisorProviderErrorCode.UNSUPPORTED_MODEL)
    if (
        response.providerRequestId != request.providerRequestId
        or response.requestId != request.requestId
        or response.promptVersion != request.promptVersion
        or response.provider is not request.provider
    ):
        return _failure(AdvisorProviderErrorCode.IDENTIFIER_MISMATCH)
    if (
        capabilities.provider is not request.provider
        or capabilities.supportsTextGeneration is not True
        or capabilities.supportsStrictJson is not True
        or capabilities.supportsToolCalling is not False
        or capabilities.supportsFunctionCalling is not False
        or capabilities.supportsStreaming is not False
        or capabilities.supportsImages is not False
        or capabilities.supportsFiles is not False
    ):
        return _failure(AdvisorProviderErrorCode.CAPABILITY_MISMATCH)
    if not _has_visible_content(response.responseText):
        return _failure(AdvisorProviderErrorCode.MALFORMED_PROVIDER_RESPONSE)
    if len(response.responseText) > min(
        request.maxOutputCharacters,
        MAX_PROVIDER_OUTPUT_CHARACTERS,
    ):
        return _failure(AdvisorProviderErrorCode.OUTPUT_TOO_LARGE)
    if response.finishReason is AdvisorProviderFinishReason.CONTENT_FILTERED:
        return _failure(AdvisorProviderErrorCode.CONTENT_FILTERED)
    if response.finishReason in {
        AdvisorProviderFinishReason.OUTPUT_LIMIT,
        AdvisorProviderFinishReason.CANCELLED,
        AdvisorProviderFinishReason.UNKNOWN,
    }:
        return _failure(AdvisorProviderErrorCode.INCOMPLETE_RESPONSE)
    if response.finishReason is AdvisorProviderFinishReason.PROVIDER_ERROR:
        return _failure(AdvisorProviderErrorCode.PROVIDER_UNAVAILABLE)
    if response.finishReason is not AdvisorProviderFinishReason.COMPLETED:
        return _failure(AdvisorProviderErrorCode.INCOMPLETE_RESPONSE)
    return AdvisorRawResponse(
        requestId=request.requestId,
        promptVersion=request.promptVersion,
        responseFormatVersion="1.0",
        responseText=response.responseText,
        receivedAt=received_at.value,
    )
