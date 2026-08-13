from datetime import datetime, timezone

from backend.supervisor.contracts import (
    CapitalSource,
    DomainSnapshot,
    Freshness,
    MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot,
    SupervisorAgentId,
)
from backend.supervisor.conversation_contracts import SupervisorConversationRequest
from backend.supervisor.conversation_service import SupervisorConversationService
from backend.supervisor.provider import ProviderAvailability, ProviderIdentity, ProviderResult
from backend.supervisor.provider_configuration import (
    SupervisorProviderConfiguration,
    SupervisorProviderMode,
)
from backend.supervisor.provider_status import (
    LLMInterpretationStatus,
    SupervisorCoreStatus,
    build_provider_status,
    derive_core_status,
    derive_llm_status,
)

NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


class AvailableProvider:
    @property
    def identity(self):
        return ProviderIdentity("available-provider", "1.0")

    @property
    def availability(self):
        return ProviderAvailability.AVAILABLE

    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        return ProviderResult(None)


class UnavailableProvider(AvailableProvider):
    @property
    def availability(self):
        return ProviderAvailability.UNAVAILABLE


class RaisingAvailabilityProvider(AvailableProvider):
    @property
    def availability(self):
        raise RuntimeError("provider transport exploded")


def disabled_config():
    return SupervisorProviderConfiguration(mode=SupervisorProviderMode.DISABLED)


def enabled_config():
    return SupervisorProviderConfiguration(mode=SupervisorProviderMode.OLLAMA_LOCAL)


def test_disabled_provider_means_core_available_and_llm_disabled_with_no_effect():
    status = build_provider_status(disabled_config(), None, provider_detail={
        "provider": "DISABLED", "availability": "UNAVAILABLE", "operationalEffect": "NONE",
    })
    assert status["supervisorCore"] == SupervisorCoreStatus.AVAILABLE.value
    assert status["llmStatus"] == LLMInterpretationStatus.DISABLED.value
    assert status["providerConfigured"] is True
    assert status["providerEnabled"] is False
    assert status["providerAvailable"] is False
    assert status["llmInterpretationAvailable"] is False
    assert status["operationalEffect"] == "NONE"
    assert status["provider"] == "DISABLED"
    assert status["availability"] == "UNAVAILABLE"


def test_enabled_provider_maps_available_unavailable_and_error_to_distinct_llm_status():
    assert derive_llm_status(enabled_config(), AvailableProvider()) is LLMInterpretationStatus.AVAILABLE
    assert derive_llm_status(enabled_config(), UnavailableProvider()) is LLMInterpretationStatus.UNAVAILABLE
    assert derive_llm_status(enabled_config(), RaisingAvailabilityProvider()) is LLMInterpretationStatus.ERROR


def test_enabled_configuration_without_provider_is_llm_unavailable_not_core_down():
    assert derive_llm_status(enabled_config(), None) is LLMInterpretationStatus.UNAVAILABLE
    assert derive_core_status(None) is SupervisorCoreStatus.AVAILABLE


def test_core_status_is_available_regardless_of_provider_state():
    assert derive_core_status(None) is SupervisorCoreStatus.AVAILABLE
    assert derive_core_status(AvailableProvider()) is SupervisorCoreStatus.AVAILABLE
    assert derive_core_status(UnavailableProvider()) is SupervisorCoreStatus.AVAILABLE
    assert derive_core_status(RaisingAvailabilityProvider()) is SupervisorCoreStatus.AVAILABLE


def test_build_provider_status_preserves_existing_provider_detail_keys():
    detail = {
        "provider": "OLLAMA_LOCAL", "model": "qwen3:4b-instruct",
        "availability": "AVAILABLE", "localhostOnly": True, "mode": "SHADOW",
        "lastCheckedAt": None, "lastSuccessAt": None, "lastFailureCode": None,
        "operationalEffect": "NONE",
    }
    status = build_provider_status(enabled_config(), AvailableProvider(), provider_detail=detail)
    for key, value in detail.items():
        assert status[key] == value
    assert status["llmStatus"] == LLMInterpretationStatus.AVAILABLE.value
    assert status["supervisorCore"] == SupervisorCoreStatus.AVAILABLE.value
    assert status["providerEnabled"] is True
    assert status["providerAvailable"] is True
    assert status["llmInterpretationAvailable"] is True


def snapshot():
    domain = DomainSnapshot(freshness=Freshness.FRESH, evaluatedAt=NOW)
    return ReadOnlySupervisorSnapshot(
        capturedAt=NOW,
        overallFreshness=Freshness.FRESH,
        bot=domain, loop=domain, trade=domain, governance=domain, emergency=domain,
        execution=domain, market=domain, decision=domain, health=domain,
        moneyManagement=MoneyManagementSnapshot(
            capitalAuthority="MONEY_MANAGEMENT",
            capitalSource=CapitalSource.PAPER,
            equity="1000",
            availableCapital="900",
            riskBudget="10",
            evaluatedAt=NOW,
            authorityFresh=True,
            freshness=Freshness.FRESH,
        ),
    )


class SnapshotAdapter:
    def build(self, app):
        return snapshot()


def test_provider_unavailable_conversation_is_degraded_while_core_remains_available():
    service = SupervisorConversationService(
        snapshot_adapter=SnapshotAdapter(), provider=None, clock=lambda: NOW
    )
    request = SupervisorConversationRequest(
        agentId=SupervisorAgentId.MM_SUPERVISOR,
        message="状態を説明して",
        conversationId="conv-core-llm",
        requestedAt=NOW,
    )
    result = service.respond(object(), request)
    assert result.status.value == "UNAVAILABLE"
    assert result.operationalEffect == "NONE"
    assert result.configurationChanged is False
    assert derive_core_status(None) is SupervisorCoreStatus.AVAILABLE
