"""Explicit, network-free transport boundary for the OpenAI adapter."""

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Tuple

from pydantic import Field

from backend.ai_advisor.provider_models import AdvisorProviderContractModel


class OpenAITransportRequest(AdvisorProviderContractModel):
    model: str = Field(min_length=1, max_length=128)
    input: str = Field(min_length=1, max_length=64_000)
    timeoutSeconds: float = Field(gt=0, le=120, allow_inf_nan=False)
    maxOutputTokens: int = Field(ge=1, le=16_384)
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    responseFormat: str
    stream: bool


class OpenAITransport(Protocol):
    def invoke(self, request: OpenAITransportRequest) -> Any:
        """Perform exactly one provider call and return an opaque response."""


class OpenAITransportTimeout(Exception):
    pass


class OpenAITransportAuthenticationError(Exception):
    pass


class OpenAITransportRateLimitError(Exception):
    pass


class OpenAITransportConnectionError(Exception):
    pass


class OpenAITransportRejectedError(Exception):
    pass


class OpenAITransportConfigurationError(Exception):
    pass


class OpenAITransportInternalError(Exception):
    pass


@dataclass
class DeterministicOpenAITransport:
    """Test transport with no I/O, retries, clock, or random state."""

    response: Any = None
    exception: Exception | None = None
    calls: list[OpenAITransportRequest] = field(default_factory=list)

    def invoke(self, request: OpenAITransportRequest) -> Any:
        validated = OpenAITransportRequest.model_validate(
            request.model_dump(warnings=False)
        )
        self.calls.append(validated)
        if self.exception is not None:
            raise self.exception
        return self.response

    @property
    def recordedRequests(self) -> Tuple[OpenAITransportRequest, ...]:
        return tuple(self.calls)


def extract_response_mapping(value: Any) -> Mapping[str, Any]:
    """Accept only a plain mapping at the transport boundary."""

    if not isinstance(value, dict):
        raise ValueError("provider response validation failed")
    return value
