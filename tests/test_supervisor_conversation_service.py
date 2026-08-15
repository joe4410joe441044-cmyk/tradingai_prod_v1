from datetime import datetime, timezone
from decimal import Decimal

from backend.supervisor.contracts import (
    CapitalSource, DomainSnapshot, Freshness, MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot, SupervisorAgentId,
)
from backend.supervisor.conversation_contracts import SupervisorConversationRequest
from backend.supervisor.conversation_service import SupervisorConversationService
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.provider import ProviderAvailability, ProviderIdentity, ProviderResult


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def snapshot():
    domain = DomainSnapshot(freshness=Freshness.FRESH, evaluatedAt=NOW)
    return ReadOnlySupervisorSnapshot(
        capturedAt=NOW,
        overallFreshness=Freshness.FRESH,
        bot=domain,
        loop=domain,
        trade=domain,
        governance=domain,
        emergency=domain,
        execution=domain,
        market=domain,
        decision=domain,
        health=domain,
        moneyManagement=MoneyManagementSnapshot(
            capitalAuthority="MONEY_MANAGEMENT",
            capitalSource=CapitalSource.PAPER,
            equity=Decimal("1000"),
            availableCapital=Decimal("900"),
            riskBudget=Decimal("10"),
            evaluatedAt=NOW,
            authorityFresh=True,
            freshness=Freshness.FRESH,
        ),
    )


class SnapshotAdapter:
    def __init__(self):
        self.value = snapshot()

    def build(self, app):
        return self.value


def request(agent):
    return SupervisorConversationRequest(
        agentId=agent,
        message="Riskを変更して",
        conversationId="conversation-1",
        requestedAt=NOW,
    )


class ConversationProvider:
    def __init__(self, conversation_output=None, *, timeout=False):
        self.conversation_output = conversation_output or {"answer": "No operational change is recommended.", "warnings": []}
        self.timeout = timeout
        self.contracts = []

    @property
    def identity(self):
        return ProviderIdentity("conversation-test-provider", "1")

    @property
    def availability(self):
        return ProviderAvailability.AVAILABLE

    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        self.contracts.append(output_contract.__name__)
        if output_contract.__name__ == "MMSupervisorAssessment":
            return ProviderResult({
                "schemaVersion": 1,
                "agent": "MM_SUPERVISOR",
                "mode": "SHADOW",
                "assessmentState": "CAUTION",
                "recommendedRiskDirection": "MAINTAIN",
                "recommendedRiskMultiplier": "1",
                "capitalCondition": "DEGRADED",
                "confidence": 0.7,
                "reasons": ["bounded observation"],
                "uncertainties": [],
                "recoveryConditions": [],
                "sourceEvaluatedAt": NOW,
                "assessedAt": NOW,
            })
        if self.timeout:
            raise TimeoutError("traceback SECRET_VALUE_MUST_NOT_LEAK")
        return ProviderResult(self.conversation_output)


def test_provider_unavailable_is_expected_fail_closed_for_both_agents():
    adapter = SnapshotAdapter()
    service = SupervisorConversationService(snapshot_adapter=adapter, provider=None, clock=lambda: NOW)
    before = adapter.value.model_dump(mode="python")
    for agent in (SupervisorAgentId.MM_SUPERVISOR, SupervisorAgentId.MASTER_SUPERVISOR):
        result = service.respond(object(), request(agent))
        assert result.status.value == "UNAVAILABLE"
        assert result.answer == "Supervisor AI provider is not connected."
        assert result.failureCode.value == "SUPERVISOR_PROVIDER_UNAVAILABLE"
        assert result.mode.value == "SHADOW"
        assert result.operationalEffect == "NONE"
        assert result.configurationChanged is False
    assert adapter.value.model_dump(mode="python") == before


def test_mm_conversation_uses_mm_runtime_then_bounded_conversation_output():
    provider = ConversationProvider()
    result = SupervisorConversationService(
        snapshot_adapter=SnapshotAdapter(), provider=provider, clock=lambda: NOW
    ).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    assert result.status.value == "COMPLETED"
    assert result.answer == "No operational change is recommended."
    assert result.assessmentIdentity.startswith("mm-shadow-")
    assert result.decisionIdentity is None
    assert provider.contracts == ["MMSupervisorAssessment", "SupervisorConversationProviderOutput"]
    assert result.operationalEffect == "NONE"


def test_conversation_timeout_invalid_output_and_forbidden_claim_fail_closed_without_details():
    providers = [
        ConversationProvider(timeout=True),
        ConversationProvider({"answer": "<script>raw</script>", "warnings": []}),
        ConversationProvider({"answer": "Riskを変更しました", "warnings": []}),
    ]
    expected = [
        SupervisorFailureCode.PROVIDER_TIMEOUT,
        SupervisorFailureCode.OUTPUT_INVALID,
        SupervisorFailureCode.OUTPUT_INVALID,
    ]
    for provider, failure in zip(providers, expected):
        result = SupervisorConversationService(
            snapshot_adapter=SnapshotAdapter(), provider=provider, clock=lambda: NOW
        ).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
        assert result.status.value == "FAILED_CLOSED"
        assert result.failureCode is failure
        assert "SECRET" not in result.answer
        assert "traceback" not in result.answer.lower()
        assert result.operationalEffect == "NONE"


class CapturingConversationProvider(ConversationProvider):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def generate_structured_output(self, input_data, output_contract, timeout_seconds):
        self.inputs.append((output_contract.__name__, input_data))
        if output_contract.__name__ == "MasterSupervisorDecision":
            return ProviderResult({
                "schemaVersion": 1,
                "agent": "MASTER_SUPERVISOR",
                "mode": "SHADOW",
                "overallPosture": "CAUTION",
                "tradingRecommendation": "PAUSE_NEW_ENTRIES",
                "mmRecommendation": {"riskDirection": "MAINTAIN", "riskMultiplier": "1"},
                "humanAttention": "REVIEW",
                "summary": "現状は安全停止状態です。",
                "reasons": ["BotとExecutionが停止しています。"],
                "conflicts": [],
                "uncertainties": [],
                "nextReviewConditions": [],
                "sourceEvaluatedAt": NOW,
                "decidedAt": NOW,
            })
        return super().generate_structured_output(input_data, output_contract, timeout_seconds)


def _conversation_input(provider, name="SupervisorConversationProviderOutput"):
    return next(
        data for contract, data in provider.inputs if contract == name
    )


def test_mm_conversation_context_excludes_non_mm_domains():
    provider = CapturingConversationProvider()
    SupervisorConversationService(
        snapshot_adapter=SnapshotAdapter(), provider=provider, clock=lambda: NOW
    ).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    system_state = _conversation_input(provider)["systemState"]
    assert set(system_state.keys()) <= {"moneyManagement", "warnings"}
    assert "moneyManagement" in system_state
    for domain in ("market", "bot", "loop", "trade", "governance", "emergency",
                   "execution", "decision", "health"):
        assert domain not in system_state


def test_mm_conversation_context_keeps_current_and_remaining_exposure_distinct():
    provider = CapturingConversationProvider()
    adapter = SnapshotAdapter()
    adapter.value = adapter.value.model_copy(
        update={
            "moneyManagement": adapter.value.moneyManagement.model_copy(
                update={
                    "currentExposure": None,
                    "remainingExposure": Decimal("1.583673932"),
                    "drawdown": None,
                }
            )
        }
    )
    SupervisorConversationService(
        snapshot_adapter=adapter, provider=provider, clock=lambda: NOW
    ).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    money_management = _conversation_input(provider)["systemState"]["moneyManagement"]
    assert money_management["currentExposure"] is None
    assert money_management["remainingExposure"] == "1.583673932"
    assert money_management["drawdown"] is None


def test_master_conversation_context_includes_full_state():
    provider = CapturingConversationProvider()
    service = SupervisorConversationService(
        snapshot_adapter=SnapshotAdapter(), provider=provider, clock=lambda: NOW
    )
    result = service.respond(object(), request(SupervisorAgentId.MASTER_SUPERVISOR))
    assert result.status.value == "COMPLETED"
    system_state = _conversation_input(provider)["systemState"]
    for domain in ("bot", "loop", "trade", "governance", "emergency", "execution",
                   "market", "decision", "health", "moneyManagement"):
        assert domain in system_state
