"""REAL-004: STOPPED pending-order authority read-only evidence selection.

Proves the CASE A/B/C/D contract for a STOPPED runtime whose process-local
stopped-PAPER durability snapshot has aged past its freshness bound:

  A. fresh authoritative real-account evidence proving FLAT + NONE -> SAFE
  B. fresh authoritative evidence showing a pending order         -> BLOCKED
  C. no trustworthy authoritative evidence                         -> UNKNOWN
  D. stale lower-priority snapshot + fresh higher-priority source  -> fresh wins

The absolute safety invariant (never `pendingOrder=false` alone => SAFE) is
covered explicitly. The existing stopped-PAPER authority remains the first
choice whenever it is fresh and can prove the state.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from backend.bot_manager.bot_manager import BotManager


def _fresh_live_account(**changes):
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
        "authorityEvaluatedAt": datetime.now(timezone.utc).isoformat(),
    }
    account.update(changes)
    return account


def _stale_stopped_paper_state(reason="SNAPSHOT_STALE"):
    return {
        "applies": True,
        "safe": False,
        "reason": reason,
        "position_state": "FLAT",
        "pending_order_state": None,
        "open_order_state": None,
        "snapshot_timestamp_state": {"valid": False, "reason": reason},
    }


def _stopped_manager(saved_mode="paper", observation=None):
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
    manager.production_ams_mm_config_provider = lambda: {}
    manager.auto_market_selection_observation = observation
    return manager


def _read_with_stale_snapshot(manager, stale_state=None):
    with patch.object(
        manager,
        "_stopped_paper_authoritative_safety_state",
        return_value=stale_state or _stale_stopped_paper_state(),
    ):
        return manager.get_authoritative_pending_order_state()


def test_case_a_stale_paper_snapshot_uses_fresh_read_only_account_safe():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(),
        "productionIntegration": {"status": "READY"},
    })
    result = _read_with_stale_snapshot(manager)
    assert result["known"] is True
    assert result["pending"] is False
    assert result["safe"] is True
    assert result["reason"] == "STOPPED_LIVE_GET_ONLY_SAFE"
    assert result["source"] == "live_account_read_only"
    assert result["pending_order"] is False


def test_case_b_fresh_authoritative_pending_order_is_blocked_never_safe():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(
            pendingOrderState="EXISTS",
        ),
    })
    result = _read_with_stale_snapshot(manager)
    assert result["known"] is True
    assert result["pending"] is True
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_EXISTS"
    assert result["source"] == "live_account_read_only"


def test_case_c_no_trustworthy_authority_stays_unknown():
    manager = _stopped_manager(observation=None)
    manager.refresh_production_ams_read_model = Mock(return_value=None)
    result = _read_with_stale_snapshot(manager)
    assert result["known"] is False
    assert result["pending"] is None
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_AUTHORITY_UNAVAILABLE"
    assert result["source"] == "live_account_read_only"


def test_safety_invariant_pending_false_alone_never_becomes_safe():
    manager = _stopped_manager(observation=None)
    manager.pending_order = False
    manager.refresh_production_ams_read_model = Mock(return_value=None)
    result = _read_with_stale_snapshot(manager)
    assert result["safe"] is False
    assert result["known"] is False


def test_safety_invariant_stale_live_account_never_becomes_safe():
    # A present-but-stale real-account snapshot proves nothing; the result must
    # remain UNKNOWN and must never be upgraded to SAFE.
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(authorityFresh=False),
    })
    result = _read_with_stale_snapshot(manager)
    assert result["safe"] is False
    assert result["known"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_AUTHORITY_STALE"
    assert result["source"] == "live_account_read_only"


def test_malformed_live_authority_fails_closed_with_truthful_provenance():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": {"authorityFresh": True},
    })
    manager.refresh_production_ams_read_model = Mock(return_value={
        "liveAccountAuthority": {"authorityFresh": True},
    })
    result = _read_with_stale_snapshot(manager)
    assert result["known"] is False
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_AUTHORITY_STALE"
    assert result["source"] == "live_account_read_only"


def test_future_live_authority_timestamp_fails_closed():
    future = _fresh_live_account(
        authorityEvaluatedAt="2099-01-01T00:00:00+00:00",
    )
    manager = _stopped_manager(observation={"liveAccountAuthority": future})
    manager.refresh_production_ams_read_model = Mock(return_value={
        "liveAccountAuthority": future,
    })
    result = _read_with_stale_snapshot(manager)
    assert result["known"] is False
    assert result["safe"] is False
    assert result["reason"] == "LIVE_PENDING_ORDER_AUTHORITY_STALE"
    assert result["source"] == "live_account_read_only"


def test_safety_invariant_open_real_position_never_becomes_safe():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(
            openPositionState="OPEN",
        ),
    })
    result = _read_with_stale_snapshot(manager)
    assert result["safe"] is False
    assert result["known"] is False


def test_case_d_fresh_authority_wins_over_durable_stale_snapshot():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(),
    })
    result = _read_with_stale_snapshot(
        manager,
        _stale_stopped_paper_state("DURABLE_SNAPSHOT_STALE"),
    )
    assert result["known"] is True
    assert result["safe"] is True
    assert result["source"] == "live_account_read_only"


def test_case_d_fresh_authority_blocked_wins_over_stale_snapshot():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(
            pendingOrderState="EXISTS",
        ),
    })
    result = _read_with_stale_snapshot(manager)
    assert result["known"] is True
    assert result["pending"] is True
    assert result["safe"] is False


def test_fresh_stopped_paper_authority_is_preferred_over_account_read():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(),
    })
    fresh_state = {
        "safe": True,
        "reason": "STOPPED_PAPER_AUTHORITATIVE_SAFE",
        "pending_order_state": "flat",
        "position_state": "FLAT",
        "snapshot_timestamp_state": {"valid": True},
    }
    with patch.object(
        manager,
        "_stopped_paper_authoritative_safety_state",
        return_value=fresh_state,
    ), patch.object(
        manager, "_stopped_live_pending_order_authority"
    ) as live:
        result = manager.get_authoritative_pending_order_state()
    live.assert_not_called()
    assert result["safe"] is True
    assert result["source"] == "stopped_paper_authoritative"


def test_unconfigured_read_model_does_not_consult_account_authority():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(),
    })
    manager.production_ams_mm_config_provider = None
    with patch.object(
        manager, "_stopped_live_pending_order_authority"
    ) as live:
        result = _read_with_stale_snapshot(manager)
    live.assert_not_called()
    assert result["safe"] is False
    assert result["known"] is False


def test_read_only_recovery_never_arms_real_order_authority():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(),
    })
    _read_with_stale_snapshot(manager)
    assert manager.config["realOrderAllowed"] is False
    assert manager.config["executionRealOrderEnabled"] is False
    assert manager.config["autoTradeEnabled"] is False


def test_status_projection_preserves_repaired_authority_fields():
    manager = _stopped_manager(observation={
        "liveAccountAuthority": _fresh_live_account(),
    })
    authority = _read_with_stale_snapshot(manager)
    projected = manager._pending_order_status_state(authority)
    assert projected["known"] is True
    assert projected["pending"] is False
    assert projected["safe"] is True
    assert projected["reason"] == "STOPPED_LIVE_GET_ONLY_SAFE"
    assert projected["source"] == "live_account_read_only"
    assert projected["engineAvailable"] is False
