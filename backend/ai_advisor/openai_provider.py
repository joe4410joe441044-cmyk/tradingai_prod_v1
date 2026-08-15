"""OpenAI-specific request/response conversion with an injected transport."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from backend.ai_advisor.provider_config import ProviderConnectionConfig, ProviderName
from backend.ai_advisor.provider_models import (
    PROVIDER_RESPONSE_VERSION,
    AdvisorProviderFinishReason,
    AdvisorProviderRequest,
    AdvisorProviderResponse,
)
from backend.ai_advisor.provider_transport import (
    OpenAITransport,
    OpenAITransportAuthenticationError,
    OpenAITransportConnectionError,
    OpenAITransportConfigurationError,
    OpenAITransportInternalError,
    OpenAITransportRateLimitError,
    OpenAITransportRejectedError,
    OpenAITransportRequest,
    OpenAITransportTimeout,
    extract_response_mapping,
)


class OpenAIProviderFailureCode(str, Enum):
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    MALFORMED_PROVIDER_RESPONSE = "MALFORMED_PROVIDER_RESPONSE"
    INTERNAL_PROVIDER_FAILURE = "INTERNAL_PROVIDER_FAILURE"


class OpenAIProviderInvocationError(ValueError):
    """Carries a safe classification, never an upstream exception message."""

    def __init__(self, code: OpenAIProviderFailureCode):
        self.code = code
        super().__init__("advisor provider unavailable")


def _finish_reason(value: Any) -> AdvisorProviderFinishReason:
    mapping = {
        "completed": AdvisorProviderFinishReason.COMPLETED,
        "stop": AdvisorProviderFinishReason.COMPLETED,
        "length": AdvisorProviderFinishReason.OUTPUT_LIMIT,
        "content_filter": AdvisorProviderFinishReason.CONTENT_FILTERED,
        "cancelled": AdvisorProviderFinishReason.CANCELLED,
    }
    if value is None:
        return AdvisorProviderFinishReason.COMPLETED
    if not isinstance(value, str) or value not in mapping:
        return AdvisorProviderFinishReason.UNKNOWN
    return mapping[value]


@dataclass(frozen=True)
class OpenAIProviderAdapter:
    config: ProviderConnectionConfig
    transport: OpenAITransport

    def __post_init__(self) -> None:
        try:
            config = ProviderConnectionConfig.model_validate(
                self.config.model_dump(warnings=False)
            )
        except Exception:
            raise ValueError("advisor provider configuration invalid") from None
        if config.provider is not ProviderName.OPENAI or config.enabled is not True:
            raise ValueError("advisor provider configuration invalid")
        object.__setattr__(self, "config", config)

    def generate(self, request: AdvisorProviderRequest) -> AdvisorProviderResponse:
        try:
            trusted_request = AdvisorProviderRequest.model_validate(
                request.model_dump(warnings=False)
            )
        except Exception:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.CONFIGURATION_INVALID
            ) from None
        if (
            trusted_request.modelId != self.config.model
            or trusted_request.timeoutSeconds != self.config.timeoutSeconds
        ):
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.CONFIGURATION_INVALID
            )
        transport_request = OpenAITransportRequest(
            requestId=trusted_request.requestId,
            providerRequestId=trusted_request.providerRequestId,
            model=self.config.model,
            input=trusted_request.renderedPrompt,
            timeoutSeconds=self.config.timeoutSeconds,
            maxOutputTokens=self.config.maxOutputTokens,
            temperature=self.config.temperature,
            responseFormat="json_object",
            stream=False,
        )
        try:
            raw = self.transport.invoke(transport_request)
        except OpenAITransportTimeout:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.TIMEOUT
            ) from None
        except OpenAITransportAuthenticationError:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.AUTHENTICATION_FAILURE
            ) from None
        except OpenAITransportRateLimitError:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.RATE_LIMITED
            ) from None
        except OpenAITransportConnectionError:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.CONNECTION_FAILURE
            ) from None
        except OpenAITransportRejectedError:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.PROVIDER_REJECTED
            ) from None
        except OpenAITransportConfigurationError:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.CONFIGURATION_INVALID
            ) from None
        except OpenAITransportInternalError:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.INTERNAL_PROVIDER_FAILURE
            ) from None
        except Exception:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.INTERNAL_PROVIDER_FAILURE
            ) from None
        try:
            payload = extract_response_mapping(raw)
            text = payload["output_text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError
            if len(text) > trusted_request.maxOutputCharacters:
                raise ValueError
            finish_reason = _finish_reason(payload.get("finish_reason"))
            return AdvisorProviderResponse(
                providerResponseVersion=PROVIDER_RESPONSE_VERSION,
                providerRequestId=trusted_request.providerRequestId,
                requestId=trusted_request.requestId,
                promptVersion=trusted_request.promptVersion,
                provider=trusted_request.provider,
                modelId=trusted_request.modelId,
                responseText=text,
                finishReason=finish_reason,
            )
        except Exception:
            raise OpenAIProviderInvocationError(
                OpenAIProviderFailureCode.MALFORMED_PROVIDER_RESPONSE
            ) from None
