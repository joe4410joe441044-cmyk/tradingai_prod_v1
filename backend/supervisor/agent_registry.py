"""Immutable initial Supervisor registry."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Type

from .contracts import MasterSupervisorDecision, MMSupervisorAssessment, SupervisorAgentId, SupervisorMode
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode


class DataSource(str, Enum):
    SUPERVISOR_SNAPSHOT = "SUPERVISOR_SNAPSHOT"
    MM_SUPERVISOR_ASSESSMENT = "MM_SUPERVISOR_ASSESSMENT"
    SUPERVISOR_DECISION_HISTORY = "SUPERVISOR_DECISION_HISTORY"
    MONEY_MANAGEMENT_SNAPSHOT = "MONEY_MANAGEMENT_SNAPSHOT"
    MONEY_MANAGEMENT_HISTORY = "MONEY_MANAGEMENT_HISTORY"


class Capability(str, Enum):
    READ_STATUS = "READ_STATUS"
    EXPLAIN_STATUS = "EXPLAIN_STATUS"
    PRODUCE_SHADOW_DECISION = "PRODUCE_SHADOW_DECISION"
    PRODUCE_SHADOW_ASSESSMENT = "PRODUCE_SHADOW_ASSESSMENT"
    ANSWER_CONVERSATION = "ANSWER_CONVERSATION"


class ProhibitedAction(str, Enum):
    SUBMIT_ORDER = "SUBMIT_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    REPLACE_ORDER = "REPLACE_ORDER"
    CHANGE_POSITION = "CHANGE_POSITION"
    CHANGE_QUANTITY = "CHANGE_QUANTITY"
    CHANGE_RISK = "CHANGE_RISK"
    CHANGE_LEVERAGE = "CHANGE_LEVERAGE"
    CHANGE_EXPOSURE = "CHANGE_EXPOSURE"
    CHANGE_MM_CONFIGURATION = "CHANGE_MM_CONFIGURATION"
    CHANGE_GOVERNANCE = "CHANGE_GOVERNANCE"
    OVERRIDE_GOVERNANCE = "OVERRIDE_GOVERNANCE"
    UNLOCK_EMERGENCY = "UNLOCK_EMERGENCY"
    ENABLE_AUTO_TRADE = "ENABLE_AUTO_TRADE"
    START_LOOP = "START_LOOP"
    STOP_LOOP = "STOP_LOOP"
    CHANGE_TRADE_MODE = "CHANGE_TRADE_MODE"
    CHANGE_ACTIVE_SYMBOL = "CHANGE_ACTIVE_SYMBOL"
    READ_SECRETS = "READ_SECRETS"
    WRITE_FILES = "WRITE_FILES"
    EXECUTE_SHELL = "EXECUTE_SHELL"
    MODIFY_SOURCE_CODE = "MODIFY_SOURCE_CODE"
    INSTALL_PACKAGES = "INSTALL_PACKAGES"
    PROMOTE_OWN_MODE = "PROMOTE_OWN_MODE"


ALL_PROHIBITED_ACTIONS = tuple(ProhibitedAction)


@dataclass(frozen=True)
class ProviderPolicy:
    required: bool
    networkAllowed: bool
    secretsAllowedInMetadata: bool


@dataclass(frozen=True)
class AgentRegistration:
    agentId: SupervisorAgentId
    displayName: str
    role: str
    contractVersion: int
    allowedDataSources: tuple[DataSource, ...]
    allowedCapabilities: tuple[Capability, ...]
    prohibitedActions: tuple[ProhibitedAction, ...]
    outputContract: Type
    enabledModes: tuple[SupervisorMode, ...]
    providerPolicy: ProviderPolicy


class SupervisorRegistry:
    def __init__(self, registrations: tuple[AgentRegistration, ...]) -> None:
        entries: dict[SupervisorAgentId, AgentRegistration] = {}
        for registration in registrations:
            if registration.agentId in entries:
                raise ValueError(f"duplicate agent ID: {registration.agentId.value}")
            entries[registration.agentId] = registration
        self._entries: Mapping[SupervisorAgentId, AgentRegistration] = MappingProxyType(entries)

    @property
    def registrations(self) -> tuple[AgentRegistration, ...]:
        return tuple(self._entries.values())

    def get(self, agent_id: SupervisorAgentId | str) -> AgentRegistration:
        try:
            typed_id = agent_id if isinstance(agent_id, SupervisorAgentId) else SupervisorAgentId(agent_id)
            return self._entries[typed_id]
        except (ValueError, KeyError) as exc:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.UNKNOWN_AGENT, "unknown Supervisor agent"
            ) from exc


_POLICY = ProviderPolicy(required=False, networkAllowed=False, secretsAllowedInMetadata=False)

REGISTRY = SupervisorRegistry((
    AgentRegistration(
        SupervisorAgentId.MASTER_SUPERVISOR, "Master Supervisor", "system oversight", 1,
        (DataSource.SUPERVISOR_SNAPSHOT, DataSource.MM_SUPERVISOR_ASSESSMENT,
         DataSource.SUPERVISOR_DECISION_HISTORY),
        (Capability.READ_STATUS, Capability.EXPLAIN_STATUS,
         Capability.PRODUCE_SHADOW_DECISION, Capability.ANSWER_CONVERSATION),
        ALL_PROHIBITED_ACTIONS, MasterSupervisorDecision, (SupervisorMode.SHADOW,), _POLICY,
    ),
    AgentRegistration(
        SupervisorAgentId.MM_SUPERVISOR, "MM Supervisor", "money-management oversight", 1,
        (DataSource.MONEY_MANAGEMENT_SNAPSHOT, DataSource.MONEY_MANAGEMENT_HISTORY),
        (Capability.READ_STATUS, Capability.EXPLAIN_STATUS,
         Capability.PRODUCE_SHADOW_ASSESSMENT, Capability.ANSWER_CONVERSATION),
        ALL_PROHIBITED_ACTIONS, MMSupervisorAssessment, (SupervisorMode.SHADOW,), _POLICY,
    ),
))


def get_agent_registration(agent_id: SupervisorAgentId | str) -> AgentRegistration:
    return REGISTRY.get(agent_id)
