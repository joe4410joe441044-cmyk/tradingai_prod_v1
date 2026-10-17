"""Work AA: STOPPED-state next-START authority parity.

A committed ``savedMode`` is the canonical destination for the NEXT START.
While STOPPED, the readiness projection must describe that same destination
without granting any real-order authority. While RUNNING, the attached runtime
mode remains authoritative even if the saved destination differs.

These tests are isolated. They never START a runtime, ARM LIVE, construct a
real execution engine, or place an order.
"""

import os

os.environ.setdefault("TEST_MODE", "1")

from types import SimpleNamespace

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


def _stopped_manager(tmp_path, selected="paper", dry_run=True):
    manager = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    manager.engine = None
    manager.config = {"mode": selected, "dry_run": dry_run}
    manager.lifecycle_state = "STOPPED"
    manager.loop_state = "STOPPED"
    manager._running = False
    manager.pending_order = False
    return manager


def _running_manager(tmp_path, runtime_mode, saved_mode):
    manager = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    manager.engine = SimpleNamespace(
        mode=runtime_mode,
        paper_fills=[],
        trade_history=[],
    )
    manager.config = {
        "mode": runtime_mode,
        "dry_run": runtime_mode == "paper",
    }
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "RUNNING"
    manager._running = True
    manager.pending_order = False
    manager.set_saved_mode(saved_mode)
    return manager


# =========================
# CASE A
# =========================

def test_stopped_selected_paper_saved_live_projects_next_start_live(tmp_path):
    manager = _stopped_manager(tmp_path, selected="paper", dry_run=True)
    manager.set_saved_mode("LIVE")

    resolution = manager._resolve_start_mode({
        "mode": "paper",
        "dry_run": True,
    })
    status = manager.get_status()

    assert resolution["mode"] == "live"
    assert resolution["authoritative"] is True
    assert status["nextStartMode"] == "LIVE"
    assert status["nextStartModeSource"] == "SAVED_MODE"
    assert status["savedMode"] == SAVED_MODE_LIVE
    assert status["selectedMode"] == "PAPER"
    assert status["runtimeMode"] == "NONE"
    assert status["liveReadiness"]["selectedMode"] == "LIVE"
    assert status["liveReadiness"]["dryRun"] is False
    assert "SELECTED_MODE_NOT_LIVE" not in status["liveBlockReasons"]
    assert "DRY_RUN_ACTIVE" not in status["liveBlockReasons"]
    assert status["realOrderAllowed"] is False
    assert status["liveOrderEntryAllowed"] is False
    assert status["executionEntryAllowed"] is False
    assert status["loopEnabled"] is False
    assert status["autoTradeEnabled"] is False


# =========================
# CASE B
# =========================

def test_stopped_selected_live_saved_paper_projects_next_start_paper(tmp_path):
    manager = _stopped_manager(tmp_path, selected="live", dry_run=False)
    manager.set_saved_mode("LIVE")
    manager.set_saved_mode("PAPER")

    resolution = manager._resolve_start_mode({
        "mode": "live",
        "dry_run": False,
    })
    status = manager.get_status()

    assert resolution["mode"] == "paper"
    assert resolution["authoritative"] is True
    assert status["nextStartMode"] == "PAPER"
    assert status["nextStartModeSource"] == "SAVED_MODE"
    assert status["savedMode"] == SAVED_MODE_PAPER
    assert status["selectedMode"] == "LIVE"
    assert status["runtimeMode"] == "NONE"
    assert status["liveReadiness"]["selectedMode"] == "PAPER"
    assert status["liveReadiness"]["dryRun"] is True
    assert "SELECTED_MODE_NOT_LIVE" in status["liveBlockReasons"]
    assert status["realOrderAllowed"] is False


# =========================
# CASE C / CASE D
# =========================

def test_running_live_runtime_stays_live_authority(tmp_path):
    manager = _running_manager(tmp_path, runtime_mode="live", saved_mode="PAPER")

    status = manager.get_status()

    assert status["status"] == "RUNNING"
    assert status["runtimeMode"] == "LIVE"
    assert status["selectedMode"] == "LIVE"
    assert status["liveReadiness"]["selectedMode"] == "LIVE"
    assert status["nextStartMode"] == "PAPER"
    assert "SELECTED_MODE_NOT_LIVE" not in status["liveBlockReasons"]


def test_running_paper_runtime_stays_paper_authority(tmp_path):
    manager = _running_manager(tmp_path, runtime_mode="paper", saved_mode="LIVE")

    status = manager.get_status()

    assert status["status"] == "RUNNING"
    assert status["runtimeMode"] == "PAPER"
    assert status["selectedMode"] == "PAPER"
    assert status["liveReadiness"]["selectedMode"] == "PAPER"
    assert status["nextStartMode"] == "LIVE"
    assert "SELECTED_MODE_NOT_LIVE" in status["liveBlockReasons"]


# =========================
# CASE E
# =========================

def test_no_saved_authority_preserves_fail_closed_fallback(tmp_path):
    manager = _stopped_manager(tmp_path, selected="paper", dry_run=True)

    assert manager.saved_mode_revision == 0
    status = manager.get_status()

    assert status["nextStartMode"] == "PAPER"
    assert status["nextStartModeSource"] == "SELECTED_MODE"
    assert status["liveReadiness"]["selectedMode"] == "PAPER"
    assert status["realOrderAllowed"] is False


def test_invalid_saved_authority_never_defaults_to_live(tmp_path):
    manager = _stopped_manager(tmp_path, selected="paper", dry_run=True)
    manager.saved_mode = "SIMULATION"
    manager.saved_mode_revision = 5

    resolution = manager._resolve_start_mode({
        "mode": "paper",
        "dry_run": True,
    })
    status = manager.get_status()

    assert resolution["mode"] == "paper"
    assert status["nextStartMode"] == "PAPER"
    assert status["nextStartModeSource"] == "SELECTED_MODE"
    assert status["realOrderAllowed"] is False


# =========================
# CASE F
# =========================

def test_stopped_saved_live_disarmed_keeps_execution_fail_closed(tmp_path):
    manager = _stopped_manager(tmp_path, selected="paper", dry_run=True)
    manager.config.update({
        "liveRuntimeStartAllowed": False,
        "liveOrderEntryAllowed": False,
        "executionEntryAllowed": False,
        "realOrderAllowed": False,
    })
    manager.set_saved_mode("LIVE")

    status = manager.get_status()

    assert status["nextStartMode"] == "LIVE"
    assert status["realOrderAllowed"] is False
    assert status["liveOrderEntryAllowed"] is False
    assert status["executionEntryAllowed"] is False
    assert status["liveRuntimeStartAllowed"] is False
    assert status["executionEnabled"] is False
    assert status["loopEnabled"] is False
    assert status["autoTradeEnabled"] is False


# =========================
# Parity / compatibility
# =========================

def test_next_start_mode_parity_with_start_resolver(tmp_path):
    cases = (
        ("paper", True, "LIVE"),
        ("live", False, "LIVE"),
        ("live", False, "PAPER"),
        ("paper", True, "PAPER"),
    )
    for selected, dry_run, saved in cases:
        manager = _stopped_manager(
            tmp_path,
            selected=selected,
            dry_run=dry_run,
        )
        manager.set_saved_mode(saved)

        status = manager.get_status()
        resolution = manager._resolve_start_mode({
            "mode": selected,
            "dry_run": dry_run,
        })

        assert status["nextStartMode"] == resolution["mode"].upper()
        assert status["liveReadiness"]["selectedMode"] == status["nextStartMode"]
        assert status["liveReadiness"]["dryRun"] == resolution["dryRun"]


def test_status_response_accepts_next_start_fields(tmp_path):
    manager = _stopped_manager(tmp_path)
    manager.set_saved_mode("LIVE")

    response = StatusResponse(**manager.get_status())

    assert response.nextStartMode == "LIVE"
    assert response.nextStartModeSource == "SAVED_MODE"
    assert response.runtimeMode == "NONE"
    assert response.realOrderAllowed is False
