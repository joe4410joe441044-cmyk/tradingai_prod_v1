"""TR-OP-A-DASH-4A: LIVE Start pre-authority contract (backend).

The authoritative pre-start LIVE permission is the global ALLOW_LIVE +
TRADE_MODE permission, plus a disabled dry_run for LIVE requests.  A LIVE
start must fail closed (before any start side effect) when that authority is
false, missing, or unknown.  Mode selection alone is never authority, and a
denied LIVE request must never silently fall back to PAPER or dryRun, nor
relax execution/real-order authority.

All tests are isolated mocks; no production runtime mutation.
"""

import os

os.environ.setdefault("TEST_MODE", "1")

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from backend import config as backend_config
from backend.bot_manager.bot_manager import BotManager
from backend.money_management.enums import (
    MoneyManagementProfile,
    RiskBlockReason,
    TradingMode,
)
from backend.money_management.leverage_authority import (
    resolve_effective_leverage,
)
from backend.money_management.models import MoneyManagementConfig


def D(value):
    return Decimal(str(value))


def _mm_config(maximum_leverage=D("5")):
    return MoneyManagementConfig(
        MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
        TradingMode.PAPER,
        D("1000"), D(".50"), D("100"), D("5"), D("20"), D("10"),
        maximum_leverage, False,
    )


def _bare_manager(**attrs):
    manager = BotManager.__new__(BotManager)
    manager.engine = None
    manager.production_ams_mm_config_provider = None
    manager.money_management_config_provider = None
    for name, value in attrs.items():
        setattr(manager, name, value)
    return manager


def _live_config(**overrides):
    config = {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "live",
        "dry_run": False,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 5,
        "sl_percent": 0.5,
        "tp_percent": 1,
        "timeframe": "5m",
        "trailing_stop": True,
        "leverage": 4.0,
    }
    config.update(overrides)
    return config


def _live_authorized_manager():
    return _bare_manager(
        money_management_config_provider=lambda: _mm_config(D("5")),
    )


def _assert_live_rejected(result, reason):
    assert result["status"] == "error"
    assert result["reason"] == reason
    assert result["success"] is False
    assert result["completed"] is False
    assert result["stateUnknown"] is False


# =========================
# 1. PAPER behavior preserved (LIVE gate does not touch PAPER)
# =========================

def test_paper_start_never_hits_live_gate():
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("5")),
    )
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(
                {"leverage": 4, "mode": "paper", "dry_run": False}
            )
    assert result["status"] == "error"
    # PAPER must hit the PAPER dry-run gate, never a LIVE rejection.
    assert result["reason"] == "PAPER_DRY_RUN_REQUIRED"


def test_paper_start_with_dry_run_reaches_pending_authority_not_live_gate():
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("5")),
    )
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(
                {"leverage": 4, "mode": "paper", "dry_run": True}
            )
    # Never rejected by the LIVE gate; PAPER path only.
    assert result["reason"] not in {
        "LIVE_NOT_ENABLED", "TRADE_MODE_NOT_LIVE", "LIVE_DRY_RUN_REQUIRED",
        "INVALID_MODE",
    }


# =========================
# 2/3. LIVE denied when global/existing LIVE authority false / unavailable
# =========================

def test_live_denied_when_allow_live_false():
    manager = _live_authorized_manager()
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(_live_config())
    _assert_live_rejected(result, "LIVE_NOT_ENABLED")


def test_live_denied_when_trade_mode_not_live():
    manager = _live_authorized_manager()
    with patch.object(backend_config, "ALLOW_LIVE", True):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(_live_config())
    _assert_live_rejected(result, "TRADE_MODE_NOT_LIVE")


# =========================
# 4. LIVE denied before any start side effect
# =========================

def test_live_rejection_happens_before_side_effects():
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("5")),
    )
    ws = Mock()
    ws.connected = False
    ws.start = Mock()
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            with patch(
                "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
                return_value=ws,
            ) as create_ws:
                result = manager.start(_live_config())
    _assert_live_rejected(result, "LIVE_NOT_ENABLED")
    assert manager.engine is None
    assert manager.lifecycle_state == "STOPPED"
    assert manager.session_id == 0
    assert manager.config == {}
    create_ws.assert_not_called()
    ws.start.assert_not_called()


# =========================
# 5. Mode selector / request alone does not authorize LIVE
# =========================

def test_live_selection_alone_does_not_authorize():
    manager = _live_authorized_manager()
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(_live_config())
    _assert_live_rejected(result, "LIVE_NOT_ENABLED")


# =========================
# 6. Invalid mode fails closed
# =========================

def test_invalid_mode_fails_closed():
    manager = _live_authorized_manager()
    result = manager.start({"leverage": 4, "mode": "simulation"})
    _assert_live_rejected(result, "INVALID_MODE")


# =========================
# 7/8. No silent fallback / conversion
# =========================

def test_no_live_to_paper_fallback():
    manager = _live_authorized_manager()
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(_live_config())
    # Must be rejected as LIVE, never accepted as PAPER.
    _assert_live_rejected(result, "LIVE_NOT_ENABLED")


def test_no_live_to_dryrun_conversion():
    manager = _live_authorized_manager()
    with patch.object(backend_config, "ALLOW_LIVE", True):
        with patch.object(backend_config, "TRADE_MODE", "live"):
            result = manager.start(_live_config(dry_run=True))
    _assert_live_rejected(result, "LIVE_DRY_RUN_REQUIRED")


# =========================
# 9/10. Denied LIVE does not relax execution/real-order authority
# =========================

def test_live_rejection_does_not_enable_execution_or_real_orders():
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("5")),
    )
    with patch.object(backend_config, "ALLOW_LIVE", False):
        with patch.object(backend_config, "TRADE_MODE", "paper"):
            result = manager.start(_live_config())
    _assert_live_rejected(result, "LIVE_NOT_ENABLED")
    assert manager.engine is None
    assert manager.config == {}
    assert manager.config.get("execution_enabled") is None


# =========================
# 11/12/13. Leverage boundary stays BLOCK (A-R1), never clamps
# =========================

@pytest.mark.parametrize("requested", ["0", "-1"])
def test_requested_leverage_zero_or_negative_blocked(requested):
    result = resolve_effective_leverage(D(requested), D("5"))
    assert result.allowed is False
    assert result.effective_leverage is None
    assert result.block_reason is RiskBlockReason.MAXIMUM_LEVERAGE


def test_requested_leverage_above_mm_max_blocked_not_clamped():
    result = resolve_effective_leverage(D("10"), D("5"))
    assert result.allowed is False
    assert result.effective_leverage is None
    assert result.maximum_leverage == D("5")
    assert result.block_reason is RiskBlockReason.MAXIMUM_LEVERAGE


def test_requested_leverage_at_or_below_mm_max_allowed():
    result = resolve_effective_leverage(D("5"), D("5"))
    assert result.allowed is True
    assert result.effective_leverage == D("5")


# LIVE DISARMED runtime/order authority separation

def test_live_disarmed_rejects_loop_or_auto_intent_before_side_effects():
    manager = _live_authorized_manager()
    manager.get_authoritative_pending_order_state = Mock(return_value={
        "known": True, "pending": False, "safe": True,
    })
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ):
        result = manager.start(_live_config(loop_on_start=True))
    _assert_live_rejected(
        result, "LIVE_DISARMED_REQUIRES_LOOP_AND_AUTO_OFF"
    )


def test_live_disarmed_blocks_auto_trade_mutation():
    manager = _bare_manager(
        config={
            "mode": "live",
            "liveOrderEntryAllowed": False,
        },
    )
    result = manager.set_execution_enabled(True)
    assert result == {
        "success": False,
        "reason": "LIVE_ORDER_ENTRY_DISARMED",
        "execution_enabled": False,
    }


def test_start_config_rejects_live_automation_intent():
    from pydantic import ValidationError
    from backend.api.bot_api import StartConfig

    with pytest.raises(ValidationError, match="LIVE_DISARMED_REQUIRES_LOOP_AND_AUTO_OFF"):
        StartConfig(**_live_config(loop_on_start=True))


def test_execution_engine_final_guard_blocks_disarmed_live_before_mm():
    from Bot.engine.execution_engine import ExecutionEngine

    engine = ExecutionEngine.__new__(ExecutionEngine)
    engine.mode = "live"
    engine.config = {
        "realOrderAllowed": False,
        "executionEntryAllowed": False,
        "liveOrderEntryAllowed": False,
    }
    allowed, rejection = engine._evaluate_execution_entry_guard({
        "symbol": "XRPUSDTM", "side": "BUY", "qty": 1,
    })
    assert allowed is False
    assert rejection["reason"] == "LIVE_ORDER_ENTRY_DISARMED"
    assert rejection["providerCall"] is False
    assert rejection["exchangeCall"] is False
