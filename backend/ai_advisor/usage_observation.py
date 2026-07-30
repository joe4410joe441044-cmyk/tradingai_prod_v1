"""Secret-free, internal-only provider usage observation contracts."""

from dataclasses import dataclass, field
from enum import Enum
import re
from threading import Lock
from typing import Optional, Protocol

from pydantic import ConfigDict, field_validator, model_validator

from backend.ai_advisor.provider_models import AdvisorProviderContractModel


class UsageObservationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    USAGE_UNAVAILABLE = "USAGE_UNAVAILABLE"


class SafeProviderName(str, Enum):
    OPENAI = "openai"


class SafeEndpointClassification(str, Enum):
    OFFICIAL_OPENAI = "official_openai"


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_IDENTIFIER_PREFIXES = (
    "apikey",
    "api_key",
    "authorization",
    "bearer",
    "sk-",
)


def safe_metadata_identifier(value: str) -> str:
    normalized = value.lower()
    if (
        not _SAFE_IDENTIFIER.fullmatch(value)
        or normalized.startswith(_FORBIDDEN_IDENTIFIER_PREFIXES)
        or "://" in normalized
    ):
        raise ValueError("provider metadata identifier invalid")
    return value


class ProviderMetadataObservation(AdvisorProviderContractModel):
    """Strict, secret-free metadata projected from one provider response."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    requestId: Optional[str] = None
    model: str
    provider: SafeProviderName
    endpointClassification: SafeEndpointClassification

    @field_validator("requestId", "model")
    @classmethod
    def validate_safe_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return safe_metadata_identifier(value)


class ProviderMetadataObservationSink(Protocol):
    def observe(self, observation: ProviderMetadataObservation) -> None:
        """Accept one strict, secret-free provider metadata observation."""


@dataclass(frozen=True)
class NoOpProviderMetadataObservationSink:
    def observe(self, observation: ProviderMetadataObservation) -> None:
        return None


@dataclass
class RecordingProviderMetadataObservationSink:
    _observation: ProviderMetadataObservation | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def observe(self, observation: ProviderMetadataObservation) -> None:
        trusted = ProviderMetadataObservation.model_validate(
            observation.model_dump(warnings=False)
        )
        with self._lock:
            if self._observation is not None:
                raise ValueError("provider metadata observation already recorded")
            self._observation = trusted

    @property
    def observation(self) -> ProviderMetadataObservation | None:
        with self._lock:
            return self._observation


def project_sdk_metadata(
    response: object,
    *,
    model: str,
) -> ProviderMetadataObservation:
    """Project only a safe SDK response ID and the confirmed request model."""

    request_id = getattr(response, "_request_id", None)
    try:
        return ProviderMetadataObservation(
            requestId=request_id,
            model=model,
            provider=SafeProviderName.OPENAI,
            endpointClassification=SafeEndpointClassification.OFFICIAL_OPENAI,
        )
    except Exception:
        return ProviderMetadataObservation(
            requestId=None,
            model=model,
            provider=SafeProviderName.OPENAI,
            endpointClassification=SafeEndpointClassification.OFFICIAL_OPENAI,
        )


class AdvisorTokenUsage(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    inputTokens: int
    outputTokens: int
    totalTokens: int

    @model_validator(mode="after")
    def validate_counts(self) -> "AdvisorTokenUsage":
        values = (self.inputTokens, self.outputTokens, self.totalTokens)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        ):
            raise ValueError("usage counts invalid")
        if self.totalTokens != self.inputTokens + self.outputTokens:
            raise ValueError("usage total invalid")
        return self


class UsageObservation(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    status: UsageObservationStatus
    usage: Optional[AdvisorTokenUsage] = None

    @model_validator(mode="after")
    def validate_status(self) -> "UsageObservation":
        if (self.status is UsageObservationStatus.AVAILABLE) != (
            self.usage is not None
        ):
            raise ValueError("usage observation invariant failed")
        return self


class UsageObservationSink(Protocol):
    def observe(self, observation: UsageObservation) -> None:
        """Accept one secret-free usage observation."""


@dataclass(frozen=True)
class NoOpUsageObservationSink:
    def observe(self, observation: UsageObservation) -> None:
        return None


@dataclass
class RecordingUsageObservationSink:
    """Thread-safe single-assignment sink for one isolated request."""

    _observation: UsageObservation | None = field(default=None, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def observe(self, observation: UsageObservation) -> None:
        trusted = UsageObservation.model_validate(
            observation.model_dump(warnings=False)
        )
        with self._lock:
            if self._observation is not None:
                raise ValueError("usage observation already recorded")
            self._observation = trusted

    @property
    def observation(self) -> UsageObservation | None:
        with self._lock:
            return self._observation


def project_sdk_usage(response: object) -> UsageObservation:
    """Project only strict aggregate token counts from an SDK response."""

    try:
        usage = getattr(response, "usage")
        value = AdvisorTokenUsage(
            inputTokens=getattr(usage, "input_tokens"),
            outputTokens=getattr(usage, "output_tokens"),
            totalTokens=getattr(usage, "total_tokens"),
        )
        return UsageObservation(
            status=UsageObservationStatus.AVAILABLE,
            usage=value,
        )
    except Exception:
        return UsageObservation(
            status=UsageObservationStatus.USAGE_UNAVAILABLE,
        )
