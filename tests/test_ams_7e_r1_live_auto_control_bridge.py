from dataclasses import replace
from decimal import Decimal

import pytest

from backend.api.bot_api import router
from backend.auto_market_selection import (
    LiveAutoActivationApproval,
    LiveAutoRuntimeObservation,
    LiveAutoSelectionRuntime,
)
from backend.auto_market_selection.live_account_authority import (
    ExistingKucoinLiveAccountAuthority,
)
from backend.auto_market_selection.live_read_only import LiveReadOnlyValidation
from backend.bot_manager.bot_manager import BotManager
from backend.runtime.governance_runtime import governance_state


def selection_only_safety(**changes):
    value = {
        "realOrderAllowed": False,
        "dryRun": False,
        "executionRealOrderDisabled": True,
        "autoTradeDisabled": True,
        "liveAutoSwitchDisabled": False,
        "liveSelectionOnly": True,
        "emergencyAvailable": True,
        "governanceAvailable": True,
    }
    value.update(changes)
    return value


def stopped_live_safety(**changes):
    value = selection_only_safety(
        liveAutoSwitchDisabled=True,
        liveSelectionOnly=False,
        stoppedLiveMonitoring=True,
    )
    value.update(changes)
    return value


def test_control_routes_are_the_only_new_public_operations():
    paths = {route.path for route in router.routes}
    assert {
        "/live-auto/approve", "/live-auto/start", "/live-auto/stop",
    }.issubset(paths)


def test_selection_only_observation_keeps_order_firewall_closed():
    validation = object.__new__(LiveReadOnlyValidation)
    validation.safety_provider = selection_only_safety
    validation._preflight()

    authority = object.__new__(ExistingKucoinLiveAccountAuthority)
    authority.safety_provider = selection_only_safety
    authority._preflight()

    for unsafe in (
        {"realOrderAllowed": True},
        {"executionRealOrderDisabled": False},
        {"autoTradeDisabled": False},
        {"liveSelectionOnly": False},
    ):
        validation.safety_provider = lambda unsafe=unsafe: selection_only_safety(
            **unsafe
        )
        with pytest.raises(RuntimeError, match="LIVE_READ_ONLY_PREFLIGHT_BLOCKED"):
            validation._preflight()


def test_stopped_live_get_only_monitoring_is_not_a_mode_conflict():
    validation = object.__new__(LiveReadOnlyValidation)
    validation.safety_provider = stopped_live_safety
    validation._preflight()

    authority = object.__new__(ExistingKucoinLiveAccountAuthority)
    authority.safety_provider = stopped_live_safety
    authority._preflight()


def test_stopped_live_pending_none_comes_from_fresh_exchange_authority():
    manager = BotManager()
    manager.config = {
        "mode": "live", "dry_run": False,
        "realOrderAllowed": False, "autoTradeEnabled": False,
        "executionRealOrderEnabled": False,
    }
    manager.lifecycle_state = "STOPPED"
    manager._running = False
    manager.engine = None
    manager.pending_order = False
    manager.auto_market_selection_observation = None
    observed = {
        "liveAccountAuthority": {
            "sourceAuthority": "REAL_LIVE_ACCOUNT",
            "capitalAuthority": "REAL_LIVE_ACCOUNT",
            "accountFresh": True,
            "positionFresh": True,
            "authorityFresh": True,
            "pendingOrdersFresh": True,
            "snapshotConsistent": True,
            "openPositionState": "FLAT",
            "pendingOrderState": "NONE",
            "currentExposure": "0",
            "reasonCodes": [],
            "authorityEvaluatedAt": "2099-01-01T00:00:00Z",
        },
        "productionIntegration": {"status": "READY"},
    }
    manager.refresh_production_ams_read_model = lambda **kwargs: observed
    result = manager.get_authoritative_pending_order_state()
    assert result["known"] is True
    assert result["pending"] is False
    assert result["safe"] is True
    assert result["reason"] == "STOPPED_LIVE_GET_ONLY_SAFE"
    assert result["source"] == "live_account_read_only"


def test_stopped_live_get_failure_remains_unknown_fail_closed():
    manager = BotManager()
    manager.config = {
        "mode": "live", "dry_run": False,
        "realOrderAllowed": False, "autoTradeEnabled": False,
        "executionRealOrderEnabled": False,
    }
    manager.lifecycle_state = "STOPPED"
    manager._running = False
    manager.engine = None
    manager.pending_order = False
    manager.auto_market_selection_observation = None
    manager.refresh_production_ams_read_model = lambda **kwargs: {
        "productionIntegration": {"status": "BLOCKED"},
    }
    result = manager.get_authoritative_pending_order_state()
    assert result["known"] is False
    assert result["pending"] is None
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_AUTHORITY_UNAVAILABLE"


def test_paper_stopped_pending_authority_regression():
    manager = BotManager()
    result = manager.get_authoritative_pending_order_state()
    assert result["known"] is True
    assert result["pending"] is False
    assert result["safe"] is True


def test_expiring_approval_is_one_shot_runtime_authority():
    seconds = [100.0]
    approval = LiveAutoActivationApproval(
        True,
        "ams-live-auto/v1",
        "1970-01-01T00:01:00Z",
        "operator:ams-7e-r1",
        "EXPLICIT_OPERATOR_APPROVAL",
        "1970-01-01T00:03:20Z",
    )
    runtime = LiveAutoSelectionRuntime(
        active_symbol_provider=lambda: "ETHUSDT",
        approval=approval,
        clock=lambda: seconds[0],
    )
    observation = LiveAutoRuntimeObservation(
        candidate_symbol="BTCUSDT",
        candidate_score=Decimal("0.92"),
        active_market_score=Decimal("0.50"),
        runtime_id="runtime-1",
        ranking_cycle_id="ranking-1",
        observation_id="observation-1",
    )
    assert runtime.get_status()["approvalState"] == "APPROVED"
    seconds[0] = 201.0
    result = runtime.observe(replace(observation))
    assert result["approvalState"] == "EXPIRED"
    assert "OPERATOR_APPROVAL_EXPIRED" in result["blockReasons"]
    stopped = runtime.restart()
    assert stopped["liveAutoEnabled"] is False
    assert stopped["liveSwitchPermissionState"] == "NONE"


def test_bot_manager_approve_start_stop_preserves_order_firewall():
    manager = BotManager()
    original_governance = dict(governance_state)
    manager.config = {
        "mode": "live",
        "dry_run": False,
        "autoTradeEnabled": False,
        "executionRealOrderEnabled": False,
        "realOrderAllowed": False,
    }
    manager._running = True
    manager._active_symbol = "ETHUSDT"
    manager.active_runtime_id = "runtime-1"
    manager.engine = object()
    manager.auto_market_selection_observation = {
        "liveAccountAuthority": {
            "openPositionState": "FLAT",
            "pendingOrderState": "NONE",
            "authorityFresh": True,
        },
        "capitalEligibility": {"authorityFresh": True},
    }
    manager.refresh_production_ams_read_model = (
        lambda force=False: manager.auto_market_selection_observation
    )
    manager.get_authoritative_pending_order_state = lambda: {
        "known": True, "pending": False,
    }
    manager._live_auto_control_loop = lambda: None
    governance_state["emergency_state"] = "READY"
    governance_state["emergency_stop"] = False
    try:
        approved = manager.approve_live_auto_control(
            approval_identity="operator:ams-7e-r1",
            approval_source="EXPLICIT_OPERATOR_APPROVAL",
            ttl_seconds=600,
        )
        assert approved["accepted"] is True
        assert approved["liveAuto"]["approvalState"] == "APPROVED"
        started = manager.start_live_auto_control()
        assert started["accepted"] is True
        assert manager.config["autoTradeEnabled"] is False
        assert manager.config["executionRealOrderEnabled"] is False
        assert manager.config["realOrderAllowed"] is False
        stopped = manager.stop_live_auto_control()
        assert stopped["liveAuto"]["liveAutoEnabled"] is False
        assert stopped["liveAuto"]["liveSwitchPermissionState"] == "NONE"
    finally:
        governance_state.clear()
        governance_state.update(original_governance)


@pytest.mark.parametrize("unsafe_key", [
    "autoTradeEnabled", "executionRealOrderEnabled", "realOrderAllowed",
])
def test_live_auto_start_rejects_any_order_authority(unsafe_key):
    manager = BotManager()
    manager.config = {
        "mode": "live", "dry_run": False,
        "autoTradeEnabled": False,
        "executionRealOrderEnabled": False,
        "realOrderAllowed": False,
    }
    manager.config[unsafe_key] = True
    manager._running = True
    manager._active_symbol = "ETHUSDT"
    manager.active_runtime_id = "runtime-1"
    manager.engine = object()
    manager.get_authoritative_pending_order_state = lambda: {
        "known": True, "pending": False,
    }
    manager.auto_market_selection_observation = {
        "liveAccountAuthority": {
            "openPositionState": "FLAT", "pendingOrderState": "NONE",
            "authorityFresh": True,
        },
        "capitalEligibility": {"authorityFresh": True},
    }
    result = manager.start_live_auto_control()
    assert result["accepted"] is False
    assert result["reason"] == "LIVE_RUNTIME_START_FAILED"
