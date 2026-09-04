"""Fresh-restart START authority routing and final-boundary regressions."""

from unittest.mock import Mock, patch

import pytest

from backend import config as backend_config
from backend.bot_manager.bot_manager import BotManager


def _formal_live_account(**changes):
    account = {
        "sourceAuthority": "REAL_LIVE_ACCOUNT",
        "capitalAuthority": "REAL_LIVE_ACCOUNT",
        "accountFresh": True,
        "positionFresh": True,
        "pendingOrdersFresh": True,
        "authorityFresh": True,
        "snapshotConsistent": True,
        "openPositionState": "FLAT",
        "pendingOrderState": "NONE",
        "currentExposure": "0",
        "reasonCodes": [],
    }
    account.update(changes)
    return account


def _stopped_manager(saved_mode):
    manager = BotManager()
    manager.config = {
        "mode": saved_mode,
        "dry_run": saved_mode != "live",
        "realOrderAllowed": False,
        "executionRealOrderEnabled": False,
        "autoTradeEnabled": False,
    }
    manager.engine = None
    manager._running = False
    manager.lifecycle_state = "STOPPED"
    manager.pending_order = False
    manager.exchange_name = "kucoin"
    manager.account_read_client_exchange = "kucoin"
    return manager


def _read(manager, account):
    manager.auto_market_selection_observation = None
    manager.refresh_production_ams_read_model = Mock(return_value={
        "liveAccountAuthority": account,
        "productionIntegration": {"status": "READY"},
    })
    return manager.get_authoritative_pending_order_state(
        requested_mode="live",
        requested_dry_run=False,
        requested_exchange="kucoin",
    )


def test_saved_paper_requested_live_routes_formal_live_authority():
    manager = _stopped_manager("paper")
    with patch.object(
        manager, "_stopped_paper_authoritative_safety_state"
    ) as paper:
        result = _read(manager, _formal_live_account())
    assert result["safe"] is True
    assert result["source"] == "live_account_read_only"
    paper.assert_not_called()
    manager.refresh_production_ams_read_model.assert_called_once_with(
        force=True, requested_mode="live", requested_dry_run=False,
    )


def test_saved_live_requested_paper_keeps_paper_authority():
    manager = _stopped_manager("live")
    with patch.object(
        manager, "_stopped_live_pending_order_authority"
    ) as live:
        result = manager.get_authoritative_pending_order_state(
            requested_mode="paper", requested_dry_run=True,
        )
    assert result["source"] != "live_account_read_only"
    live.assert_not_called()


@pytest.mark.parametrize(("changes", "reason"), [
    ({"authorityFresh": False}, "LIVE_PENDING_ORDER_AUTHORITY_STALE"),
    ({"positionFresh": False}, "LIVE_PENDING_ORDER_AUTHORITY_STALE"),
    ({"reasonCodes": ["INCOMPLETE"]}, "LIVE_ACCOUNT_AUTHORITY_INCOMPLETE"),
    ({"openPositionState": "OPEN"}, "LIVE_POSITION_OPEN"),
    ({"currentExposure": "1"}, "LIVE_EXPOSURE_REMAINING"),
    ({"pendingOrderState": "EXISTS"}, "LIVE_PENDING_ORDER_EXISTS"),
])
def test_live_inventory_unsafe_states_fail_closed(changes, reason):
    result = _read(_stopped_manager("paper"), _formal_live_account(**changes))
    assert result["safe"] is False
    assert result["reason"] == reason


def test_live_inventory_query_failure_fails_closed():
    manager = _stopped_manager("paper")
    manager.auto_market_selection_observation = None
    manager.refresh_production_ams_read_model = Mock(return_value={
        "productionIntegration": {"status": "BLOCKED"},
    })
    result = manager.get_authoritative_pending_order_state(
        requested_mode="live", requested_dry_run=False,
        requested_exchange="kucoin",
    )
    assert result["known"] is False
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_AUTHORITY_UNAVAILABLE"


def test_live_exchange_identity_mismatch_fails_closed():
    manager = _stopped_manager("paper")
    manager.account_read_client_exchange = "other"
    result = _read(manager, _formal_live_account())
    assert result["safe"] is False
    assert result["reason"] == "LIVE_ACCOUNT_IDENTITY_MISMATCH"


def test_start_authority_discards_cached_ready_when_inventory_changes():
    manager = _stopped_manager("paper")
    manager.auto_market_selection_observation = {
        "liveAccountAuthority": _formal_live_account(
            authorityEvaluatedAt="2099-01-01T00:00:00Z",
        ),
    }
    manager.refresh_production_ams_read_model = Mock(return_value={
        "liveAccountAuthority": _formal_live_account(
            pendingOrderState="EXISTS",
        ),
    })
    result = manager.get_authoritative_pending_order_state(
        requested_mode="live", requested_dry_run=False,
        requested_exchange="kucoin",
    )
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_EXISTS"
    manager.refresh_production_ams_read_model.assert_called_once_with(
        force=True, requested_mode="live", requested_dry_run=False,
    )


def test_start_rechecks_inventory_before_first_side_effect():
    manager = _stopped_manager("paper")
    manager._resolve_leverage_authority = Mock(return_value=Mock(
        allowed=True, effective_leverage=1, maximum_leverage=1,
    ))
    manager._resolve_max_drawdown_authority = Mock(return_value=5.0)
    safe = {"known": True, "pending": False, "safe": True}
    changed = {
        "known": True, "pending": True, "safe": False,
        "reason": "LIVE_PENDING_ORDER_EXISTS",
    }
    manager.get_authoritative_pending_order_state = Mock(
        side_effect=[safe, changed]
    )
    manager.stop = Mock()
    config = {
        "mode": "live", "dry_run": False, "exchange": "kucoin",
        "symbol": "XRPUSDT", "leverage": 1, "max_drawdown_pct": 5,
        "loop_on_start": False, "auto_trade_on_start": False,
    }
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ):
        result = manager.start(config)
    assert result["reason"] == "LIVE_PENDING_ORDER_EXISTS"
    assert manager.get_authoritative_pending_order_state.call_count == 2
    manager.stop.assert_not_called()
    assert manager.session_id == 0
    assert manager.lifecycle_state == "STOPPED"


def test_order_authority_stays_disarmed_during_live_preflight():
    manager = _stopped_manager("paper")
    _read(manager, _formal_live_account())
    assert manager.config["realOrderAllowed"] is False
    assert manager.config["executionRealOrderEnabled"] is False
    assert manager.config["autoTradeEnabled"] is False


def test_saved_paper_without_requested_mode_uses_live_exchange_authority():
    manager = _stopped_manager("paper")
    manager.auto_market_selection_observation = None
    manager.refresh_production_ams_read_model = Mock(return_value={
        "liveAccountAuthority": _formal_live_account(),
        "productionIntegration": {"status": "READY"},
    })
    with patch.object(backend_config, "ALLOW_LIVE", True), \
         patch.object(backend_config, "TRADE_MODE", "live"), \
         patch.object(manager, "_stopped_paper_authoritative_safety_state") as paper:
        result = manager.get_authoritative_pending_order_state()
    assert result["safe"] is True
    assert result["source"] == "live_account_read_only"
    assert result["known"] is True
    assert result["pending"] is False
    assert result["reason"] == "STOPPED_LIVE_GET_ONLY_SAFE"
    paper.assert_not_called()
    manager.refresh_production_ams_read_model.assert_called_once_with(
        force=True, requested_mode="live", requested_dry_run=False,
    )


def test_saved_paper_without_requested_mode_paper_backend_stays_paper():
    manager = _stopped_manager("paper")
    with patch.object(backend_config, "ALLOW_LIVE", False), \
         patch.object(backend_config, "TRADE_MODE", "paper"), \
         patch.object(manager, "_stopped_live_pending_order_authority") as live:
        manager.get_authoritative_pending_order_state()
    live.assert_not_called()


def test_saved_paper_without_requested_mode_live_pending_order_exists_fail_closed():
    manager = _stopped_manager("paper")
    manager.auto_market_selection_observation = None
    manager.refresh_production_ams_read_model = Mock(return_value={
        "liveAccountAuthority": _formal_live_account(
            pendingOrderState="EXISTS",
        ),
        "productionIntegration": {"status": "READY"},
    })
    with patch.object(backend_config, "ALLOW_LIVE", True), \
         patch.object(backend_config, "TRADE_MODE", "live"):
        result = manager.get_authoritative_pending_order_state()
    assert result["safe"] is False
    assert result["known"] is True
    assert result["pending"] is True
    assert result["reason"] == "LIVE_PENDING_ORDER_EXISTS"
    assert result["source"] == "live_account_read_only"
