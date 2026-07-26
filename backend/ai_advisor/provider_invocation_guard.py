"""Pure fail-closed guard for live provider network invocation."""

from enum import Enum
from typing import Literal

from backend.ai_advisor.provider_config import ProviderName
from backend.ai_advisor.provider_models import AdvisorProviderContractModel


class InvocationGuardReason(str, Enum):
    NETWORK_INVOCATION_DISABLED = "NETWORK_INVOCATION_DISABLED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    PROVIDER_NOT_OPENAI = "PROVIDER_NOT_OPENAI"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    TRANSPORT_UNAVAILABLE = "TRANSPORT_UNAVAILABLE"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    ALLOWED = "ALLOWED"


class InvocationGuardInput(AdvisorProviderContractModel):
    providerEnabled: bool
    provider: ProviderName
    networkInvocationAllowed: bool = False
    credentialResolved: bool
    transportConfigured: bool
    configurationValid: bool


class InvocationGuardResult(AdvisorProviderContractModel):
    allowed: bool
    reasonCode: InvocationGuardReason
    safeMessage: Literal[
        "advisor provider invocation allowed",
        "advisor provider invocation denied",
    ]


def evaluate_invocation_guard(value: InvocationGuardInput) -> InvocationGuardResult:
    try:
        trusted = InvocationGuardInput.model_validate(value.model_dump(warnings=False))
        if trusted.networkInvocationAllowed is not True:
            reason = InvocationGuardReason.NETWORK_INVOCATION_DISABLED
        elif trusted.providerEnabled is not True:
            reason = InvocationGuardReason.PROVIDER_DISABLED
        elif trusted.provider is not ProviderName.OPENAI:
            reason = InvocationGuardReason.PROVIDER_NOT_OPENAI
        elif trusted.configurationValid is not True:
            reason = InvocationGuardReason.CONFIGURATION_INVALID
        elif trusted.transportConfigured is not True:
            reason = InvocationGuardReason.TRANSPORT_UNAVAILABLE
        elif trusted.credentialResolved is not True:
            reason = InvocationGuardReason.CREDENTIAL_UNAVAILABLE
        else:
            reason = InvocationGuardReason.ALLOWED
    except Exception:
        reason = InvocationGuardReason.CONFIGURATION_INVALID
    allowed = reason is InvocationGuardReason.ALLOWED
    return InvocationGuardResult(
        allowed=allowed,
        reasonCode=reason,
        safeMessage=(
            "advisor provider invocation allowed"
            if allowed
            else "advisor provider invocation denied"
        ),
    )
