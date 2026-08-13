"""Fail-closed authorization checks for Supervisor agents."""

from .agent_registry import Capability, DataSource, ProhibitedAction, get_agent_registration
from .contracts import SupervisorAgentId, SupervisorMode
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode


def validate_agent_capability(
    agent_id: SupervisorAgentId | str, capability: Capability | str, mode: SupervisorMode | str
) -> bool:
    registration = get_agent_registration(agent_id)
    try:
        typed_mode = mode if isinstance(mode, SupervisorMode) else SupervisorMode(mode)
    except ValueError as exc:
        raise SupervisorBoundaryError(SupervisorFailureCode.MODE_NOT_ALLOWED, "unknown mode") from exc
    if typed_mode not in registration.enabledModes:
        code = (SupervisorFailureCode.MODE_PROMOTION_PROHIBITED
                if typed_mode in (SupervisorMode.ADVISORY, SupervisorMode.ACTIVE)
                else SupervisorFailureCode.MODE_NOT_ALLOWED)
        raise SupervisorBoundaryError(code, "mode is not enabled for agent")
    try:
        typed_capability = capability if isinstance(capability, Capability) else Capability(capability)
    except ValueError as exc:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.CAPABILITY_DENIED, "unknown capability"
        ) from exc
    if typed_capability not in registration.allowedCapabilities:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.CAPABILITY_DENIED, "capability is not allowed"
        )
    return True


def validate_data_source_access(agent_id: SupervisorAgentId | str, data_source: DataSource | str) -> bool:
    registration = get_agent_registration(agent_id)
    try:
        typed_source = data_source if isinstance(data_source, DataSource) else DataSource(data_source)
    except ValueError as exc:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.DATA_SOURCE_DENIED, "unknown data source"
        ) from exc
    if typed_source not in registration.allowedDataSources:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.DATA_SOURCE_DENIED, "data source is not allowed"
        )
    return True


def assert_action_prohibited(agent_id: SupervisorAgentId | str, action: ProhibitedAction | str) -> None:
    registration = get_agent_registration(agent_id)
    try:
        typed_action = action if isinstance(action, ProhibitedAction) else ProhibitedAction(action)
    except ValueError as exc:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED, "unknown actions are prohibited"
        ) from exc
    if typed_action in registration.prohibitedActions:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.ACTION_PROHIBITED, "action is explicitly prohibited"
        )
    raise SupervisorBoundaryError(SupervisorFailureCode.FAIL_CLOSED, "action is not explicitly allowed")
