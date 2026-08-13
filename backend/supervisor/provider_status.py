"""Explicit availability separation between the deterministic Supervisor Core and the optional LLM interpretation layer.

The Supervisor Core (snapshot, diagnostics, validation, history, safety
boundaries) is available regardless of provider presence. The LLM
interpretation layer is optional and never gates the Core. This module exposes
those two states distinctly so that a disabled or unavailable provider can
never be reported as a broken Supervisor.
"""

from __future__ import annotations

from enum import Enum

from .provider import ProviderAvailability, StructuredOutputProvider
from .provider_configuration import SupervisorProviderConfiguration, SupervisorProviderMode


class SupervisorCoreStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class LLMInterpretationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


def derive_core_status(provider: StructuredOutputProvider | None) -> SupervisorCoreStatus:
    """The deterministic Core is never downgraded by provider state."""
    return SupervisorCoreStatus.AVAILABLE


def derive_llm_status(
    configuration: SupervisorProviderConfiguration,
    provider: StructuredOutputProvider | None,
) -> LLMInterpretationStatus:
    if configuration.mode is SupervisorProviderMode.DISABLED:
        return LLMInterpretationStatus.DISABLED
    if provider is None:
        return LLMInterpretationStatus.UNAVAILABLE
    try:
        availability = provider.availability
    except Exception:
        return LLMInterpretationStatus.ERROR
    if availability is ProviderAvailability.AVAILABLE:
        return LLMInterpretationStatus.AVAILABLE
    if availability is ProviderAvailability.UNAVAILABLE:
        return LLMInterpretationStatus.UNAVAILABLE
    return LLMInterpretationStatus.ERROR


def build_provider_status(
    configuration: SupervisorProviderConfiguration,
    provider: StructuredOutputProvider | None,
    *,
    provider_detail: dict | None = None,
) -> dict:
    """Merge explicit Core/LLM availability fields into a provider status payload.

    Existing provider detail keys are preserved for backward compatibility; only
    additive fields are introduced.
    """
    llm_status = derive_llm_status(configuration, provider)
    status = dict(provider_detail or {})
    status.update({
        "supervisorCore": derive_core_status(provider).value,
        "llmStatus": llm_status.value,
        "providerConfigured": True,
        "providerEnabled": configuration.mode is not SupervisorProviderMode.DISABLED,
        "providerAvailable": llm_status is LLMInterpretationStatus.AVAILABLE,
        "llmInterpretationAvailable": llm_status is LLMInterpretationStatus.AVAILABLE,
        "operationalEffect": "NONE",
    })
    return status
