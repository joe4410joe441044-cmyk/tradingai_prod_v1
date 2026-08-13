from dataclasses import FrozenInstanceError

import pytest

from backend.supervisor.agent_registry import (
    REGISTRY, AgentRegistration, Capability, DataSource, ProviderPolicy,
    SupervisorRegistry, get_agent_registration,
)
from backend.supervisor.contracts import MMSupervisorAssessment, SupervisorAgentId, SupervisorMode
from backend.supervisor.failure_codes import SupervisorBoundaryError, SupervisorFailureCode


def test_registry_has_exactly_the_two_initial_shadow_agents():
    assert tuple(item.agentId for item in REGISTRY.registrations) == (
        SupervisorAgentId.MASTER_SUPERVISOR, SupervisorAgentId.MM_SUPERVISOR,
    )
    assert all(item.enabledModes == (SupervisorMode.SHADOW,) for item in REGISTRY.registrations)
    assert Capability.READ_STATUS in get_agent_registration("MASTER_SUPERVISOR").allowedCapabilities
    assert DataSource.MONEY_MANAGEMENT_SNAPSHOT in get_agent_registration("MM_SUPERVISOR").allowedDataSources


def test_unknown_agent_fails_closed_and_registry_is_immutable():
    with pytest.raises(SupervisorBoundaryError) as caught:
        get_agent_registration("FUTURE_AGENT")
    assert caught.value.code is SupervisorFailureCode.UNKNOWN_AGENT
    with pytest.raises(FrozenInstanceError):
        REGISTRY.registrations[0].displayName = "changed"


def test_duplicate_registration_is_rejected():
    registration = AgentRegistration(
        SupervisorAgentId.MM_SUPERVISOR, "MM", "role", 1, (), (), (),
        MMSupervisorAssessment, (SupervisorMode.SHADOW,), ProviderPolicy(False, False, False),
    )
    with pytest.raises(ValueError, match="duplicate"):
        SupervisorRegistry((registration, registration))
