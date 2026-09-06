"""Secret-free production configuration contracts for AI Advisor."""

from enum import Enum
from typing import Literal, Optional, Tuple

from pydantic import Field, model_validator

from backend.ai_advisor.provider_config import (
    CredentialReference,
    ProviderName,
)
from backend.ai_advisor.provider_models import AdvisorProviderContractModel

PRODUCTION_CONFIG_VERSION = "ai-advisor-production-config/v1"

# Deliberate production-safe provider live-input budget.
#
# The serialized Advisor prompt is dominated by a fixed ~16 KB baseline
# (instruction boilerplate + runtime scalars + approved-spec metadata), so the
# historical default of 16_384 bytes left essentially zero headroom: the
# shortest canonical question (~16_090 B) already used 98% of the budget, and
# the overall-state question (16_414 B) overflowed it, so the fail-closed
# input gate rejected it before any network call (Q1 ADVISOR_PROVIDER_FAILURE).
#
# 32 KiB is selected as the smallest clean, bounded ceiling that:
#   - accepts the current canonical questions (~16.4 KB) with ~2x headroom;
#   - is far below the gpt-4o-mini context window (128K tokens) and the
#     render/transport character cap (64_000 chars) and HTTP body cap (65_536 B);
#   - keeps the fail-closed gate bounded (requests above 32 KiB are still rejected).
DEFAULT_LIVE_MAX_INPUT_BYTES = 32_768
DEFAULT_LIVE_MAX_INPUT_TOKENS = 32_768


class ProductionConfigSource(str, Enum):
    ENVIRONMENT = "ENVIRONMENT"
    INJECTED = "INJECTED"


class ProductionConfigFailureCode(str, Enum):
    AI_ADVISOR_CONFIG_INVALID = "AI_ADVISOR_CONFIG_INVALID"
    AI_ADVISOR_AUTH_CONFIG_INVALID = "AI_ADVISOR_AUTH_CONFIG_INVALID"
    AI_ADVISOR_PROVIDER_CONFIG_INVALID = "AI_ADVISOR_PROVIDER_CONFIG_INVALID"
    AI_ADVISOR_CREDENTIAL_CONFIG_INVALID = "AI_ADVISOR_CREDENTIAL_CONFIG_INVALID"
    AI_ADVISOR_TIMEOUT_CONFIG_INVALID = "AI_ADVISOR_TIMEOUT_CONFIG_INVALID"
    AI_ADVISOR_RATE_LIMIT_CONFIG_INVALID = "AI_ADVISOR_RATE_LIMIT_CONFIG_INVALID"
    AI_ADVISOR_CONCURRENCY_CONFIG_INVALID = "AI_ADVISOR_CONCURRENCY_CONFIG_INVALID"
    AI_ADVISOR_COMPOSITION_FAILED = "AI_ADVISOR_COMPOSITION_FAILED"


class AIAdvisorProductionConfig(AdvisorProviderContractModel):
    configVersion: Literal["ai-advisor-production-config/v1"]
    source: ProductionConfigSource
    endpointEnabled: bool = False
    networkInvocationAllowed: bool = False
    provider: Literal[ProviderName.OPENAI] = ProviderName.OPENAI
    model: str = Field(default="openai-advisor-model", min_length=1, max_length=128)
    credentialReference: Optional[CredentialReference] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    authenticationCredentialReference: Optional[CredentialReference] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    baseUrl: Optional[str] = Field(default=None, repr=False, exclude=True)
    principalId: str = Field(default="ai-advisor-user", min_length=1, max_length=128)
    advisorAccessAllowed: bool = True
    liveTestExplicitlyAllowed: bool = False
    liveKillSwitchActive: bool = True
    liveMaximumInputBytes: int = Field(default=DEFAULT_LIVE_MAX_INPUT_BYTES, ge=1, le=65_536)
    liveMaximumInputTokens: int = Field(default=DEFAULT_LIVE_MAX_INPUT_TOKENS, ge=1, le=65_536)
    liveMaximumOutputTokens: int = Field(default=4096, ge=1, le=16_384)
    providerTimeoutSeconds: float = Field(default=30.0, gt=0, le=120)
    endpointTimeoutSeconds: float = Field(default=35.0, gt=0, le=120)
    requestSizeLimitBytes: int = Field(default=65_536, ge=1024, le=65_536)
    rateLimitWindowSeconds: float = Field(default=60.0, gt=0, le=3600)
    rateLimitMaxRequests: int = Field(default=10, ge=1, le=100)
    concurrencyLimit: int = Field(default=2, ge=1, le=16)
    concurrencyAcquireTimeoutSeconds: float = Field(default=0.01, ge=0, le=1)

    @model_validator(mode="after")
    def validate_policy(self) -> "AIAdvisorProductionConfig":
        if not self.model.strip() or not self.principalId.strip():
            raise ValueError("production text configuration invalid")
        if self.endpointTimeoutSeconds <= self.providerTimeoutSeconds:
            raise ValueError("endpoint timeout must exceed provider timeout")
        if not self.providerTimeoutSeconds.is_integer():
            raise ValueError("provider timeout must use whole seconds")
        if self.networkInvocationAllowed and not self.endpointEnabled:
            raise ValueError("network invocation requires endpoint enablement")
        return self


class ProductionConfigLoadResult(AdvisorProviderContractModel):
    succeeded: bool
    configuration: Optional[AIAdvisorProductionConfig] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    failureCode: Optional[ProductionConfigFailureCode] = None
    safeMessage: Optional[Literal["AI Advisor configuration is invalid."]] = None

    @model_validator(mode="after")
    def validate_result(self) -> "ProductionConfigLoadResult":
        if self.succeeded:
            if (
                self.configuration is None
                or self.failureCode is not None
                or self.safeMessage is not None
            ):
                raise ValueError("configuration result invariant failed")
        elif (
            self.configuration is not None
            or self.failureCode is None
            or self.safeMessage is None
        ):
            raise ValueError("configuration result invariant failed")
        return self


class ProductionReadinessStatus(str, Enum):
    DISABLED = "DISABLED"
    READY_OFFLINE = "READY_OFFLINE"
    READY_LIVE = "READY_LIVE"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    AUTHENTICATION_UNAVAILABLE = "AUTHENTICATION_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class ProductionReadiness(AdvisorProviderContractModel):
    status: ProductionReadinessStatus
    endpointAvailable: bool
    networkInvocationAvailable: bool
    authenticationReady: bool
    providerReady: bool
    credentialReady: bool
    safeReasons: Tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class ProductionOperationalStatus(AdvisorProviderContractModel):
    enabled: bool
    status: ProductionReadinessStatus
    authenticationReady: bool
    providerReady: bool
    networkAllowed: bool
    networkReady: bool
    liveTestAllowed: bool = False
    killSwitchActive: bool = True
