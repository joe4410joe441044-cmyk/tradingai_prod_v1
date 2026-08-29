"""TR-OPERATION-CONNECT-6: selection mode runtime connection (backend).

Covers the runtime hand-off of operator-selected MANUAL/AUTO:

    Frontend selection_mode -> /bot/start request -> StartConfig
        -> start_bot() -> BotManager.start() -> BotManager.selection_mode
"""

import pytest
from pydantic import ValidationError

from backend.api import bot_api
from backend.api.bot_api import SelectionMode, StartConfig
from backend.bot_manager.bot_manager import BotManager


def _base_config(**overrides):
    payload = {
        "symbol": "xrpusdtm",
        "risk_percent": 1,
        "sl_percent": 1,
        "leverage": 5,
        "mode": "paper",
    }
    payload.update(overrides)
    return payload


# =========================
# StartConfig validation
# =========================

@pytest.mark.parametrize("value", ["MANUAL", "AUTO"])
def test_start_config_accepts_selection_mode(value):
    config = StartConfig(**_base_config(selection_mode=value))
    assert config.selection_mode.value == value


def test_start_config_defaults_selection_mode_to_manual():
    config = StartConfig(**_base_config())
    assert config.selection_mode is SelectionMode.manual
    assert config.selection_mode.value == "MANUAL"


@pytest.mark.parametrize("value", ["BOGUS", "manual", "auto", "", 123, None])
def test_start_config_rejects_invalid_selection_mode(value):
    with pytest.raises(ValidationError):
        StartConfig(**_base_config(selection_mode=value))


# =========================
# start_bot() forwarding
# =========================

def test_start_bot_forwards_selection_mode_to_bot_manager(monkeypatch):
    captured = {}

    class FakeManager:
        def start(self, config):
            captured["config"] = config
            return {"status": "started", "selectionMode": config.get("selection_mode")}

    monkeypatch.setattr(bot_api, "get_bot_manager", lambda: FakeManager())

    for value in ("MANUAL", "AUTO"):
        captured.clear()
        result = bot_api.start_bot(StartConfig(**_base_config(selection_mode=value)))
        assert captured["config"]["selection_mode"] == value
        assert result["selectionMode"] == value


# =========================
# BotManager selection mode hand-off
# =========================

class _FakeLifecycle:
    def __init__(self, manager):
        self.manager = manager
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        self.manager.selection_mode = "AUTO"
        return {"amsRuntimeState": "READY"}

    def stop(self):
        self.stopped += 1
        self.manager.selection_mode = "MANUAL"
        return {"amsRuntimeState": "STOPPED"}

    def run_one_cycle(self, *, started_at=None):
        return {"accepted": True}

    def get_status(self):
        return {"amsRuntimeState": "STOPPED"}


def test_stop_revokes_auto_selection_authority():
    manager = _bare_manager()
    manager.selection_mode = "AUTO"
    manager.shutdown_lock = __import__("threading").RLock()
    manager.stop_live_auto_control = lambda: None
    manager._set_lifecycle_state = lambda _state: None
    manager._set_loop_state = lambda _state: None
    manager.engine = None
    manager.ws = None
    manager.state = type("State", (), {"runtime_metrics": {}})()
    manager._capture_account_snapshot = lambda: None
    manager.strategy = object()
    manager.ob_manager = object()
    manager.active_runtime_id = "runtime"
    manager._running = True
    manager.account_snapshot = {}
    manager.runtime_instance_id = "runtime"
    manager.config = {"mode": "paper"}
    manager.paper_account_runtime_snapshot = {}
    manager._set_lifecycle_state = lambda _state: None
    manager.stop()
    assert manager.selection_mode == "MANUAL"
    assert manager.auto_market_selection_lifecycle.stopped == 1


def _bare_manager():
    manager = BotManager.__new__(BotManager)
    manager.selection_mode = "MANUAL"
    manager.auto_market_selection_lifecycle = _FakeLifecycle(manager)
    return manager


def test_manual_handoff_stops_auto_and_stays_manual():
    manager = _bare_manager()
    assert manager._handoff_selection_mode("MANUAL") == "MANUAL"
    assert manager.auto_market_selection_lifecycle.stopped == 1
    assert manager.auto_market_selection_lifecycle.started == 0


def test_auto_handoff_starts_auto_and_becomes_auto():
    manager = _bare_manager()
    assert manager._handoff_selection_mode("AUTO") == "AUTO"
    assert manager.auto_market_selection_lifecycle.started == 1
    assert manager.auto_market_selection_lifecycle.stopped == 0


@pytest.mark.parametrize("value", ["BOGUS", "", None, 42])
def test_invalid_or_missing_handoff_falls_back_to_manual(value):
    manager = _bare_manager()
    assert manager._handoff_selection_mode(value) == "MANUAL"
    assert manager.auto_market_selection_lifecycle.started == 0


def test_fail_closed_lifecycle_leaves_manual():
    class BlockedLifecycle(_FakeLifecycle):
        def start(self):
            self.started += 1
            return {"amsRuntimeState": "BLOCKED", "reasonCodes": ["AUTO_RUNTIME_BLOCKED"]}

    manager = BotManager.__new__(BotManager)
    manager.selection_mode = "MANUAL"
    manager.auto_market_selection_lifecycle = BlockedLifecycle(manager)
    with pytest.raises(RuntimeError, match="AUTO_RUNTIME_BLOCKED"):
        manager._handoff_selection_mode("AUTO")
    assert manager.selection_mode == "MANUAL"
    assert manager.auto_market_selection_lifecycle.stopped == 1


def test_pending_lifecycle_transitions_to_ready_without_manual_downgrade(monkeypatch):
    class PendingLifecycle(_FakeLifecycle):
        def start(self):
            self.started += 1
            if self.started == 1:
                return {"amsRuntimeState": "BLOCKED", "reasonCodes": ["AUTO_RUNTIME_PENDING_UNKNOWN"]}
            return {"amsRuntimeState": "READY", "enabled": True, "reasonCodes": []}

    manager = BotManager.__new__(BotManager)
    manager.selection_mode = "MANUAL"
    manager.auto_market_selection_lifecycle = PendingLifecycle(manager)
    monkeypatch.setattr("backend.bot_manager.bot_manager.time.sleep", lambda _seconds: None)
    assert manager._handoff_selection_mode("AUTO") == "AUTO"
    assert manager.auto_market_selection_lifecycle.started == 2


def test_pending_lifecycle_timeout_is_typed_and_stays_manual(monkeypatch):
    class PendingLifecycle(_FakeLifecycle):
        def start(self):
            self.started += 1
            return {"amsRuntimeState": "BLOCKED", "reasonCodes": ["AUTO_RUNTIME_PENDING_UNKNOWN"]}

    manager = BotManager.__new__(BotManager)
    manager.selection_mode = "MANUAL"
    manager.auto_market_selection_lifecycle = PendingLifecycle(manager)
    ticks = iter((10.0, 10.0, 12.0))
    monkeypatch.setattr("backend.bot_manager.bot_manager.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("backend.bot_manager.bot_manager.time.sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="AUTO_RUNTIME_PENDING_UNKNOWN"):
        manager._handoff_selection_mode("AUTO")
    assert manager.selection_mode == "MANUAL"
    assert manager.auto_market_selection_lifecycle.stopped == 1


def test_initial_auto_cycle_requires_accepted_typed_runtime():
    manager = _bare_manager()
    manager.selection_mode = "AUTO"
    manager.auto_market_selection_lifecycle.run_one_cycle = lambda **_kwargs: {
        "accepted": True, "reasonCodes": [], "runtime": {"amsRuntimeState": "READY"}
    }
    assert manager._run_initial_auto_market_selection_cycle()["accepted"] is True


def test_initial_auto_cycle_blocked_preserves_reason_and_mode():
    manager = _bare_manager()
    manager.selection_mode = "AUTO"
    manager.auto_market_selection_lifecycle.run_one_cycle = lambda **_kwargs: {
        "accepted": False, "reasonCodes": ["AUTO_RUNTIME_MM_UNAVAILABLE"],
        "runtime": {"amsRuntimeState": "BLOCKED"},
    }
    with pytest.raises(RuntimeError, match="AUTO_RUNTIME_MM_UNAVAILABLE"):
        manager._run_initial_auto_market_selection_cycle()
    assert manager.selection_mode == "AUTO"


# =========================
# MM capital authority force contract (AUTO readiness path)
# =========================

def test_official_mm_capital_authority_forwards_force(monkeypatch):
    manager = BotManager.__new__(BotManager)
    calls = []

    def fake_refresh(*, force=False):
        calls.append(force)
        return {"capitalEligibilityContract": None}

    manager.refresh_production_ams_read_model = fake_refresh
    manager.get_official_mm_capital_authority(force=True)
    assert calls == [True]

    manager.get_official_mm_capital_authority()
    assert calls == [True, False]
