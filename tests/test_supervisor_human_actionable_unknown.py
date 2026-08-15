from backend.supervisor.contracts import FieldValueObservation, Freshness, InputValueState, SupervisorAgentId
from backend.supervisor.human_actionable_unknown import build_actionable_unknowns
from tests.test_supervisor_conversation_service import (
    NOW, ConversationProvider, SnapshotAdapter, request, snapshot,
)
from backend.supervisor.conversation_service import SupervisorConversationService


def test_known_evidence_does_not_fabricate_unknown():
    assert build_actionable_unknowns(snapshot(), SupervisorAgentId.MASTER_SUPERVISOR) == ()


def test_unknown_has_reason_missing_information_and_safe_next_step():
    value = snapshot()
    mm = value.moneyManagement.model_copy(update={"fieldStates": (FieldValueObservation(field="ruinGuardStatus", state=InputValueState.UNKNOWN),)})
    result = build_actionable_unknowns(value.model_copy(update={"moneyManagement": mm}), SupervisorAgentId.MM_SUPERVISOR)
    assert result[0].status == "UNKNOWN"
    assert all((result[0].reason, result[0].missingInformation, result[0].safeNextStep, result[0].decisionImpact))


def test_partial_keeps_known_snapshot_and_identifies_only_missing_field():
    value = snapshot()
    before_equity = value.moneyManagement.equity
    mm = value.moneyManagement.model_copy(update={"fieldStates": (FieldValueObservation(field="drawdown", state=InputValueState.NULL),)})
    result = build_actionable_unknowns(value.model_copy(update={"moneyManagement": mm}), SupervisorAgentId.MM_SUPERVISOR)
    assert before_equity == value.moneyManagement.equity
    assert [item.evidenceField for item in result] == ["drawdown"]


def test_stale_evidence_is_not_presented_as_current():
    value = snapshot(); mm = value.moneyManagement.model_copy(update={"freshness": Freshness.STALE})
    result = build_actionable_unknowns(value.model_copy(update={"moneyManagement": mm}), SupervisorAgentId.MM_SUPERVISOR)
    assert result[0].status == "STALE" and "Freshness" in result[0].reason


def test_decision_critical_unknown_explicitly_keeps_decision_blocked():
    value = snapshot(); emergency = value.emergency.model_copy(update={"freshness": Freshness.MISSING})
    result = build_actionable_unknowns(value.model_copy(update={"emergency": emergency}), SupervisorAgentId.MASTER_SUPERVISOR)
    item = next(item for item in result if item.subject == "Emergency safety state")
    assert "実行可能とは判断せず" in item.decisionImpact


def test_provider_hallucination_is_rejected_and_machine_snapshot_unchanged():
    adapter = SnapshotAdapter()
    adapter.value = adapter.value.model_copy(update={"bot": adapter.value.bot.model_copy(update={"status": "STOPPED"})})
    before = adapter.value.model_dump(mode="python")
    provider = ConversationProvider({"answer": "Bot is running.", "warnings": []})
    result = SupervisorConversationService(snapshot_adapter=adapter, provider=provider, clock=lambda: NOW).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    assert result.status.value == "FAILED_CLOSED"
    assert adapter.value.model_dump(mode="python") == before


def test_unsafe_next_step_is_rejected():
    provider = ConversationProvider({"answer": "Next step: enable Auto Trade.", "warnings": []})
    result = SupervisorConversationService(snapshot_adapter=SnapshotAdapter(), provider=provider, clock=lambda: NOW).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    assert result.status.value == "FAILED_CLOSED"


def test_machine_state_invariance_with_actionable_explanation():
    adapter = SnapshotAdapter(); before = adapter.value.model_dump(mode="python")
    provider = ConversationProvider()
    result = SupervisorConversationService(snapshot_adapter=adapter, provider=provider, clock=lambda: NOW).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    assert result.operationalEffect == "NONE" and result.configurationChanged is False
    assert adapter.value.model_dump(mode="python") == before


def test_provider_failure_itself_is_human_actionable():
    result = SupervisorConversationService(snapshot_adapter=SnapshotAdapter(), provider=None, clock=lambda: NOW).respond(object(), request(SupervisorAgentId.MM_SUPERVISOR))
    item = result.actionableUnknowns[0]
    assert item.reason and item.missingInformation and item.safeNextStep and item.decisionImpact
