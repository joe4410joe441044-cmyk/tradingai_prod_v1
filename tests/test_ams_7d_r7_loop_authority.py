import asyncio

import pytest
from fastapi import HTTPException

from backend.api.governance import set_execution
from backend.bot_manager.bot_manager import BotManager
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)


@pytest.fixture(autouse=True)
def safe_governance_state():
    previous = dict(governance_state)
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    yield
    governance_state.clear()
    governance_state.update(previous)


def test_restart_defaults_all_authorities_off():
    manager = BotManager()

    assert manager.lifecycle_state == "STOPPED"
    assert manager.loop_state == "STOPPED"
    assert governance_state["execution_enabled"] is False


def test_bot_running_does_not_imply_loop_or_auto_trade():
    manager = BotManager()
    manager._running = True
    manager._set_lifecycle_state("RUNNING")

    assert manager.lifecycle_state == "RUNNING"
    assert manager.loop_state == "STOPPED"
    assert governance_state["execution_enabled"] is False


def test_loop_requires_bot_running_and_does_not_enable_auto_trade():
    manager = BotManager()

    rejected = manager.start_loop()
    assert rejected["reason"] == "LOOP_REQUIRES_BOT_RUNNING"

    manager._running = True
    manager._set_lifecycle_state("RUNNING")
    started = manager.start_loop()

    assert started["success"] is True
    assert manager.loop_state == "RUNNING"
    assert governance_state["execution_enabled"] is False


def test_emergency_blocks_loop_start():
    manager = BotManager()
    manager._running = True
    manager._set_lifecycle_state("RUNNING")
    governance_state["emergency_stop"] = True

    rejected = manager.start_loop()

    assert rejected["reason"] == "LOOP_BLOCKED_BY_EMERGENCY_LOCK"
    assert manager.loop_state == "STOPPED"


def test_stopping_loop_disables_auto_trade_without_stopping_bot():
    manager = BotManager()
    manager._running = True
    manager._set_lifecycle_state("RUNNING")
    manager._set_loop_state("RUNNING")
    governance_state["execution_enabled"] = True

    manager.stop_loop()

    assert manager.lifecycle_state == "RUNNING"
    assert manager._running is True
    assert manager.loop_state == "STOPPED"
    assert governance_state["execution_enabled"] is False


def test_auto_trade_requires_explicit_running_loop(monkeypatch):
    manager = BotManager()
    manager._running = True
    manager._set_lifecycle_state("RUNNING")
    monkeypatch.setattr(
        "backend.api.governance.get_bot_manager", lambda: manager
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(set_execution({"enabled": True}))
    assert error.value.status_code == 409
    assert error.value.detail["reason"] == "AUTO_TRADE_REQUIRES_LOOP_ON"

    manager.start_loop()
    result = asyncio.run(set_execution({"enabled": True}))
    assert result["execution_enabled"] is True
