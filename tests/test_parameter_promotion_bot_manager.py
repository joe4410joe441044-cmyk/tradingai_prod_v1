"""E-PARAM-5 focused tests: BotManager safe promotion boundary wiring.

The BotManager only supplies the runtime safety signal (stopped / running-flat
/ open-position) and rebuilds the runtime parameter authority after a
successful canonical promotion.  The promotion decision itself stays in the
canonical authority.
"""

from pathlib import Path

from backend.bot_manager.bot_manager import BotManager
from backend.strategy.parameters.settings_service import (
    ParameterSettingsService,
)


def _pending_service(tmp_path: Path) -> ParameterSettingsService:
    service = ParameterSettingsService(base_directory=tmp_path)
    configuration = service.configuration("PAPER")
    parameters = dict(configuration["parameters"])
    parameters["minimumCompositeScore"] = 0.42
    result = service.update_configuration(
        scope="PAPER",
        parameters=parameters,
        expected_revision=configuration["configuredRevision"],
    )
    assert result.outcome.value == "ACCEPTED"
    return service


def _bare_manager(tmp_path, *, running, position_state):
    manager = BotManager.__new__(BotManager)
    manager.config = {"mode": "paper"}
    manager._running = running
    manager.lifecycle_state = "RUNNING" if running else "STOPPED"
    manager.engine = None
    manager._parameter_promotion_service = ParameterSettingsService(
        base_directory=tmp_path
    ).promotion
    manager._execution_control_position_state = lambda: position_state
    manager._resolve_microstructure_parameter_set = lambda mode: None
    return manager


def test_bot_manager_promotes_when_stopped(tmp_path):
    service = _pending_service(tmp_path)
    manager = _bare_manager(
        tmp_path, running=False, position_state={"side": "FLAT"}
    )
    manager._parameter_promotion_service = service.promotion

    result = manager.promote_parameter_revision_if_safe()
    assert result["outcome"] == "PROMOTED"
    assert result["promoted"] is True
    assert result["runtimeRebuilt"] is True
    assert service.effective("PAPER")["effectiveRevision"] == 2


def test_bot_manager_promotes_running_flat(tmp_path):
    service = _pending_service(tmp_path)
    manager = _bare_manager(
        tmp_path, running=True, position_state={"side": "FLAT"}
    )
    manager._parameter_promotion_service = service.promotion

    result = manager.promote_parameter_revision_if_safe()
    assert result["outcome"] == "PROMOTED"
    assert service.effective("PAPER")["effectiveRevision"] == 2


def test_bot_manager_defers_promotion_while_position_open(tmp_path):
    service = _pending_service(tmp_path)
    manager = _bare_manager(
        tmp_path, running=True, position_state={"side": "LONG"}
    )
    manager._parameter_promotion_service = service.promotion

    result = manager.promote_parameter_revision_if_safe()
    assert result["outcome"] == "DEFERRED_OPEN_POSITION"
    assert result["promoted"] is False
    assert "runtimeRebuilt" not in result
    assert service.effective("PAPER")["effectiveRevision"] == 1
