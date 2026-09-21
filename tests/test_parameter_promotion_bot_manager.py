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


def test_empty_config_stopped_scope_and_exact_revision_gap(tmp_path):
    service = ParameterSettingsService(base_directory=tmp_path)
    for revision in range(2, 12):
        configured = service.configuration("PAPER")
        parameters = dict(configured["parameters"], maximumHoldMs=90000 if revision <= 5 else 60000)
        assert service.update_configuration(
            scope="PAPER", parameters=parameters,
            expected_revision=configured["configuredRevision"],
        ).outcome.value == "ACCEPTED"
        if revision == 5:
            service.promote_if_safe("PAPER", safe_to_promote=True)
    assert service.effective("PAPER")["effectiveRevision"] == 5
    assert service.effective("PAPER")["parameters"]["maximumHoldMs"] == 90000
    manager = _bare_manager(tmp_path, running=False, position_state={"side": "FLAT"})
    manager.config = {}
    result = manager.promote_parameter_revision_if_safe(bot_stopped=True, scope="PAPER")
    assert result["outcome"] == "PROMOTED"
    assert service.effective("PAPER")["effectiveRevision"] == 11
    assert service.effective("PAPER")["parameters"]["maximumHoldMs"] == 60000
    assert manager.config == {}
    assert manager._running is False
    assert manager.engine is None


def test_explicit_live_scope_remains_live(tmp_path):
    service = ParameterSettingsService(base_directory=tmp_path)
    config = service.configuration("LIVE")
    assert service.update_configuration(
        scope="LIVE", parameters=dict(config["parameters"], maximumHoldMs=60000),
        expected_revision=1, confirm_live=True,
    ).outcome.value == "ACCEPTED"
    manager = _bare_manager(tmp_path, running=False, position_state={"side": "FLAT"})
    manager.config = {}
    result = manager.promote_parameter_revision_if_safe(bot_stopped=True, scope="LIVE")
    assert result["scope"] == "LIVE"
    assert result["promoted"] is True
    assert service.effective("LIVE")["effectiveRevision"] == 2
    assert service.effective("PAPER")["effectiveRevision"] == 1


def test_explicit_scope_fails_closed(tmp_path):
    service = _pending_service(tmp_path)
    manager = _bare_manager(tmp_path, running=False, position_state={"side": "FLAT"})
    for config, scope in [({}, "UNKNOWN"), ({}, ""), ({}, 42), ({"mode": "live"}, "PAPER"), ({"mode": "invalid"}, "PAPER")]:
        manager.config = config
        result = manager.promote_parameter_revision_if_safe(bot_stopped=True, scope=scope)
        assert result["outcome"] == "INVALID_SCOPE"
        assert result["promoted"] is False
    manager.config = {}
    assert manager.promote_parameter_revision_if_safe()["outcome"] == "INVALID_SCOPE"
    assert service.effective("PAPER")["effectiveRevision"] == 1


def test_explicit_scope_cannot_bypass_running_or_open_position(tmp_path):
    _pending_service(tmp_path)
    manager = _bare_manager(tmp_path, running=True, position_state={"side": "FLAT"})
    assert manager.promote_parameter_revision_if_safe(bot_stopped=True, scope="PAPER")["outcome"] == "DEFERRED_NOT_SAFE"
    manager._running = False
    manager.lifecycle_state = "STOPPED"
    manager._execution_control_position_state = lambda: {"side": "LONG"}
    assert manager.promote_parameter_revision_if_safe(bot_stopped=True, scope="PAPER")["outcome"] == "DEFERRED_OPEN_POSITION"


def test_start_boundary_and_websocket_keep_manager_scope(tmp_path):
    service = _pending_service(tmp_path)
    manager = _bare_manager(tmp_path, running=False, position_state={"side": "FLAT"})
    assert manager.promote_parameter_revision_if_safe(bot_stopped=True)["promoted"] is True
    configured = service.configuration("PAPER")
    service.update_configuration(scope="PAPER", parameters=configured["parameters"], expected_revision=2)
    manager._running = True
    manager.lifecycle_state = "RUNNING"
    manager._last_parameter_promotion_check = 0
    manager._maybe_promote_parameter_authority_at_boundary()
    assert service.effective("PAPER")["effectiveRevision"] == 3


def test_actual_start_promotes_before_runtime_snapshot(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock
    import pytest
    from backend.bot_manager import bot_manager as module
    from backend.strategy.parameters.resolver import CanonicalParameterResolver
    from backend.strategy.parameters.runtime_registry import reset_runtime_snapshots

    service = _pending_service(tmp_path)
    manager = _bare_manager(tmp_path, running=False, position_state={"side": "FLAT"})
    manager.config = {}
    del manager._resolve_microstructure_parameter_set
    manager._canonical_parameter_resolver = CanonicalParameterResolver(base_directory=tmp_path)
    manager._resolve_leverage_authority = lambda config: SimpleNamespace(
        allowed=True, effective_leverage=1, maximum_leverage=5,
    )
    manager._resolve_max_drawdown_authority = lambda config: 5
    manager.get_authoritative_pending_order_state = lambda: {"known": True, "pending": False, "safe": True}
    manager._recheck_stale_stopped_paper_start_authority = lambda config, state: state
    manager.stop = lambda: {"status": "stopped", "success": True, "completed": True, "stateUnknown": False}
    manager._set_lifecycle_state = lambda state: setattr(manager, "lifecycle_state", state)
    manager._notify_money_management_lifecycle = lambda state: True
    manager.money_management_runtime_metrics = Mock()
    manager.session_id = 0
    manager.market_snapshot_lock = threading.Lock()
    manager._set_active_symbol_for_start = lambda symbol: symbol
    manager._prepare_real_account_snapshot_for_exchange = Mock()
    monkeypatch.setattr(module, "add_log", lambda *args: None)

    class SnapshotCaptured(BaseException):
        pass

    def after_snapshot(reason):
        assert service.effective("PAPER")["effectiveRevision"] == 2
        expected = manager._canonical_parameter_resolver.resolve_paper().to_runtime_dict()
        actual = dict(manager.microstructure_builder.parameter_set)
        actual.pop("capturedAt")
        expected.pop("capturedAt")
        assert actual == expected
        raise SnapshotCaptured()

    manager._invalidate_stopped_paper_durable_snapshot = after_snapshot
    try:
        with pytest.raises(SnapshotCaptured):
            manager.start({"mode": "paper", "dry_run": True, "symbol": "XRPUSDT"})
        assert manager.engine is None
    finally:
        reset_runtime_snapshots()
