import pytest

from backend.supervisor.agent_registry import Capability, DataSource, ProhibitedAction
from backend.supervisor.failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from backend.supervisor.security_boundary import (
    assert_action_prohibited, validate_agent_capability, validate_data_source_access,
)


@pytest.mark.parametrize("capability", ["READ_STATUS", "EXPLAIN_STATUS", "PRODUCE_SHADOW_DECISION"])
def test_master_read_and_shadow_capabilities_are_allowed(capability):
    assert validate_agent_capability("MASTER_SUPERVISOR", capability, "SHADOW")


@pytest.mark.parametrize("action", [
    "SUBMIT_ORDER", "CHANGE_MM_CONFIGURATION", "OVERRIDE_GOVERNANCE", "UNLOCK_EMERGENCY",
    "WRITE_FILES", "EXECUTE_SHELL", "INSTALL_PACKAGES", "PROMOTE_OWN_MODE",
])
def test_dangerous_actions_are_explicitly_prohibited(action):
    with pytest.raises(SupervisorBoundaryError) as caught:
        assert_action_prohibited("MASTER_SUPERVISOR", action)
    assert caught.value.code is SupervisorFailureCode.ACTION_PROHIBITED


def test_unknown_capability_and_data_source_are_denied():
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_agent_capability("MASTER_SUPERVISOR", "WRITE_STATUS", "SHADOW")
    assert caught.value.code is SupervisorFailureCode.CAPABILITY_DENIED
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_data_source_access("MM_SUPERVISOR", "ENVIRONMENT")
    assert caught.value.code is SupervisorFailureCode.DATA_SOURCE_DENIED


@pytest.mark.parametrize("mode", ["ADVISORY", "ACTIVE"])
def test_mode_promotion_is_prohibited(mode):
    with pytest.raises(SupervisorBoundaryError) as caught:
        validate_agent_capability("MASTER_SUPERVISOR", Capability.READ_STATUS, mode)
    assert caught.value.code is SupervisorFailureCode.MODE_PROMOTION_PROHIBITED
