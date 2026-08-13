"""Provider-neutral interface. No provider is initialized or contacted here."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, Type

from pydantic import BaseModel

from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode


class ProviderAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ProviderIdentity:
    name: str
    version: str


@dataclass(frozen=True)
class ProviderResult:
    output: BaseModel | None
    failureCode: SupervisorFailureCode | None = None


class StructuredOutputProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    @property
    def availability(self) -> ProviderAvailability: ...

    def generate_structured_output(
        self, input_data: Mapping[str, object], output_contract: Type[BaseModel], timeout_seconds: float
    ) -> ProviderResult: ...


def require_provider(provider: StructuredOutputProvider | None) -> StructuredOutputProvider:
    if provider is None or provider.availability is not ProviderAvailability.AVAILABLE:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.PROVIDER_UNAVAILABLE, "structured-output provider is unavailable"
        )
    return provider


def validate_provider_result(result: ProviderResult) -> BaseModel:
    if result.failureCode is not None:
        raise SupervisorBoundaryError(result.failureCode, "provider generation failed")
    if result.output is None:
        raise SupervisorBoundaryError(SupervisorFailureCode.OUTPUT_INVALID, "provider output is missing")
    return result.output
