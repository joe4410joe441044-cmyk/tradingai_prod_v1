"""Secret-free configuration contract for concrete AI Advisor providers."""

from enum import Enum
from typing import Annotated, Literal, Optional
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, field_validator, model_validator

from backend.ai_advisor.provider_models import AdvisorProviderContractModel

PROVIDER_CONNECTION_CONFIG_VERSION = "ai-advisor-provider-connection/v1"
MIN_PROVIDER_TIMEOUT_SECONDS = 1.0
MAX_PROVIDER_TIMEOUT_SECONDS = 120.0
MIN_PROVIDER_OUTPUT_TOKENS = 1
MAX_PROVIDER_OUTPUT_TOKENS = 16_384
MIN_PROVIDER_TEMPERATURE = 0.0
MAX_PROVIDER_TEMPERATURE = 2.0

TrimmedIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ProviderName(str, Enum):
    OPENAI = "OPENAI"
    MOCK = "MOCK"
    DISABLED = "DISABLED"


class CredentialSource(str, Enum):
    ENVIRONMENT = "ENVIRONMENT"
    INJECTED = "INJECTED"
    SECRET_MANAGER = "SECRET_MANAGER"
    SYSTEMD_CREDENTIAL = "SYSTEMD_CREDENTIAL"


class ProviderResponseFormat(str, Enum):
    STRICT_JSON = "STRICT_JSON"


class CredentialReference(AdvisorProviderContractModel):
    credentialId: TrimmedIdentifier
    source: CredentialSource

    @field_validator("credentialId")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("credential reference must not be empty")
        return normalized


class ProviderConnectionConfig(AdvisorProviderContractModel):
    configVersion: Literal["ai-advisor-provider-connection/v1"]
    provider: ProviderName
    model: TrimmedIdentifier
    credentialReference: Optional[CredentialReference] = None
    endpoint: Optional[Annotated[str, StringConstraints(max_length=2048)]] = None
    timeoutSeconds: Annotated[
        float,
        Field(
            ge=MIN_PROVIDER_TIMEOUT_SECONDS,
            le=MAX_PROVIDER_TIMEOUT_SECONDS,
            allow_inf_nan=False,
        ),
    ]
    maxOutputTokens: Annotated[
        int,
        Field(ge=MIN_PROVIDER_OUTPUT_TOKENS, le=MAX_PROVIDER_OUTPUT_TOKENS),
    ]
    temperature: Annotated[
        float,
        Field(
            ge=MIN_PROVIDER_TEMPERATURE,
            le=MAX_PROVIDER_TEMPERATURE,
            allow_inf_nan=False,
        ),
    ]
    responseFormat: Literal[ProviderResponseFormat.STRICT_JSON]
    enabled: bool

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model must not be empty")
        return normalized

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            not normalized
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint validation failed")
        return normalized.rstrip("/")

    @model_validator(mode="after")
    def validate_provider_state(self) -> "ProviderConnectionConfig":
        if self.provider is ProviderName.DISABLED:
            if self.enabled is not False:
                raise ValueError("disabled provider cannot be enabled")
            if self.credentialReference is not None:
                raise ValueError("disabled provider cannot use credentials")
        elif self.enabled is not True:
            raise ValueError("configured provider must be enabled")
        if self.provider is ProviderName.OPENAI and self.credentialReference is None:
            raise ValueError("OpenAI credential reference required")
        if self.provider is ProviderName.MOCK and self.credentialReference is not None:
            raise ValueError("mock provider cannot use credentials")
        return self
