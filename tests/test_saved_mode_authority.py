"""D-LIVE-2: canonical saved trading-mode authority.

These tests are isolated. They never START a runtime, ARM LIVE, construct an
execution engine, or place an order. They prove that ``savedMode`` is a pure
configuration authority for the NEXT START and that execution authority stays
fail-closed.

Contract under test:

* ``savedMode`` (PAPER | LIVE) is the committed operator destination.
* Saving it never starts the runtime and never enables execution.
* It is durable across a BotManager restart (process restart behaviour).
* It is exposed in status.
* START resolves the requested mode from ``savedMode`` once committed.
* A running PAPER engine keeps its runtime mode while ``savedMode`` changes.
"""

import os

os.environ.setdefault("TEST_MODE", "1")

import pytest

from backend.api.bot_api import StatusResponse
from backend.bot_manager.bot_manager import (
    SAVED_MODE_LIVE,
    SAVED_MODE_PAPER,
    BotManager,
)
from backend.runtime.governance_runtime import governance_state


@pytest.fixture(autouse=True)
def _reset_governance():
    saved = dict(governance_state)
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = "READY"
    governance_state["mode"] = "PAPER"
    yield
    governance_state.clear()
    governance_state.update(saved)


def _stopped_manager(**attrs):
    manager = BotManager()
    manager.engine = None
    manager.config = {"mode": "paper", "dry_run": True}
    manager.lifecycle_state = "STOPPED"
    manager.loop_state = "STOPPED"
    manager._running = False
    manager.pending_order = False
    for name, value in attrs.items():
        setattr(manager, name, value)
    return manager


def test_initial_saved_mode_is_paper():
    manager = _stopped_manager()

    assert manager.get_saved_mode() == SAVED_MODE_PAPER
    assert manager.saved_mode_revision == 0


def test_save_live_commits_saved_mode():
    manager = _stopped_manager()

    result = manager.set_saved_mode("LIVE")

    assert result["success"] is True
    assert result["savedMode"] == SAVED_MODE_LIVE
    assert manager.get_saved_mode() == SAVED_MODE_LIVE
    assert manager.saved_mode_revision == 1


def test_save_live_does_not_start_or_touch_execution_authority():
    manager = _stopped_manager()

    result = manager.set_saved_mode("LIVE")

    assert result["success"] is True
    assert manager.engine is None
    assert manager._running is False
    assert manager.lifecycle_state == "STOPPED"
    assert manager.loop_state == "STOPPED"
    assert manager.config.get("realOrderAllowed") is not True
    assert manager.config.get("liveOrderEntryAllowed") is not True
    assert manager.config.get("executionEntryAllowed") is not True
    assert governance_state["execution_enabled"] is False


def test_save_paper_returns_to_paper():
    manager = _stopped_manager()

    manager.set_saved_mode("LIVE")
    result = manager.set_saved_mode("PAPER")

    assert result["success"] is True
    assert manager.get_saved_mode() == SAVED_MODE_PAPER
    assert manager.saved_mode_revision == 2


def test_invalid_saved_mode_is_rejected():
    manager = _stopped_manager()

    result = manager.set_saved_mode("SIMULATION")

    assert result["success"] is False
    assert result["reason"] == "INVALID_SAVED_MODE"
    assert manager.get_saved_mode() == SAVED_MODE_PAPER
    assert manager.saved_mode_revision == 0


def test_stale_revision_is_rejected():
    manager = _stopped_manager()

    manager.set_saved_mode("LIVE")

    stale = manager.set_saved_mode("PAPER", expected_revision=0)
    assert stale["success"] is False
    assert stale["reason"] == "STALE_SAVED_MODE_REVISION"
    assert manager.get_saved_mode() == SAVED_MODE_LIVE

    fresh = manager.set_saved_mode("PAPER", expected_revision=1)
    assert fresh["success"] is True
    assert manager.get_saved_mode() == SAVED_MODE_PAPER


def test_status_exposes_saved_mode_and_execution_stays_fail_closed():
    manager = _stopped_manager()

    manager.set_saved_mode("LIVE")

    status = manager.get_status()
    response = StatusResponse(**status)

    assert response.savedMode == "LIVE"
    assert response.savedModeRevision == 1
    assert response.runtimeMode == "NONE"
    assert response.executionMode == "SIMULATION"
    assert response.realOrderAllowed is False
    assert response.liveOrderEntryAllowed is False
    assert response.executionEnabled is False


def test_saved_mode_is_durable_across_manager_restart(tmp_path):
    path = tmp_path / "saved_mode_authority.json"

    first = BotManager(saved_mode_path=str(path))
    assert first.get_saved_mode() == SAVED_MODE_PAPER
    first.set_saved_mode("LIVE")

    second = BotManager(saved_mode_path=str(path))
    assert second.get_saved_mode() == SAVED_MODE_LIVE
    assert second.saved_mode_revision == 1


def test_start_resolves_from_saved_mode_live():
    manager = _stopped_manager()
    manager.set_saved_mode("LIVE")

    resolution = manager._resolve_start_mode({
        "mode": "paper",
        "dry_run": True,
    })

    assert resolution["authoritative"] is True
    assert resolution["mode"] == "live"
    assert resolution["dryRun"] is False


def test_start_resolves_from_saved_mode_paper():
    manager = _stopped_manager()
    manager.set_saved_mode("LIVE")
    manager.set_saved_mode("PAPER")

    resolution = manager._resolve_start_mode({
        "mode": "live",
        "dry_run": False,
    })

    assert resolution["authoritative"] is True
    assert resolution["mode"] == "paper"
    assert resolution["dryRun"] is True


def test_start_uses_request_body_before_any_commit():
    manager = _stopped_manager()

    resolution = manager._resolve_start_mode({
        "mode": "live",
        "dry_run": False,
    })

    assert resolution["authoritative"] is False
    assert resolution["mode"] == "live"
    assert resolution["dryRun"] is False


def test_running_paper_keeps_runtime_mode_when_saved_mode_changes():
    manager = _stopped_manager()
    manager.config = {"mode": "paper", "dry_run": True}
    manager._running = True

    manager.set_saved_mode("LIVE")

    # The committed next-START destination changes, but the running engine's
    # mode is not mutated in place.
    assert manager.get_saved_mode() == SAVED_MODE_LIVE
    assert str(manager.config.get("mode")) == "paper"
