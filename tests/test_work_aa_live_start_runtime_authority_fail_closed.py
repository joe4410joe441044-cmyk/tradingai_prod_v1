# -*- coding: utf-8 -*-
"""WORK AA: LIVE START fail-closes on unknown/inconsistent runtime authority.

All tests are offline mocks.  No exchange, service, intent store or production
runtime is touched, and no order path is exercised.
"""

import os

os.environ.setdefault("TEST_MODE", "1")

from decimal import Decimal
from unittest.mock import Mock, patch

from backend import config as backend_config
from backend.bot_manager.bot_manager import BotManager
from backend.money_management.enums import (
    MoneyManagementProfile,
    TradingMode,
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


def _manager(*, lifecycle, loop, engine=None):
    manager = BotManager.__new__(BotManager)
    manager.engine = engine
    manager.lifecycle_state = lifecycle
    manager.loop_state = loop
    manager.production_ams_mm_config_provider = None
    manager.money_management_config_provider = lambda: _mm_config(D("5"))
    return manager


def _live_config():
    return {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "live",
        "dry_run": False,
        "risk_percent": 0.5,
        "position_size": 100,
        "max_drawdown_pct": 5,
        "sl_percent": 0.5,
        "tp_percent": 1,
        "timeframe": "5m",
        "trailing_stop": True,
        "leverage": 4.0,
    }


def _start(manager):
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ):
        return manager.start(_live_config())


def test_live_start_fails_closed_when_loop_runs_while_bot_stopped():
    manager = _manager(lifecycle="STOPPED", loop="RUNNING")

    result = _start(manager)

    assert result["status"] == "error"
    assert result["reason"] == "LIVE_RUNTIME_AUTHORITY_INCONSISTENT"
    assert result["success"] is False
    assert result["completed"] is False
    assert result["stateUnknown"] is False
    assert manager.engine is None
    assert manager.lifecycle_state == "STOPPED"
    assert manager.loop_state == "RUNNING"


def test_live_start_fails_closed_when_lifecycle_unknown():
    manager = _manager(lifecycle="???", loop="STOPPED")

    result = _start(manager)

    assert result["status"] == "error"
    assert result["reason"] == "LIVE_RUNTIME_AUTHORITY_UNKNOWN"
    assert result["success"] is False
    assert result["completed"] is False
    assert result["stateUnknown"] is True
    assert manager.lifecycle_state == "???"


def test_live_start_attached_loop_stopped_is_not_rewritten_to_stopped():
    manager = _manager(lifecycle="RUNNING", loop="STOPPED")
    manager.get_authoritative_pending_order_state = Mock(
        return_value={
            "known": True,
            "pending": False,
            "safe": False,
            "reason": "TEST_PENDING_AUTHORITY_STOP",
        }
    )

    result = _start(manager)

    assert result["reason"] not in {
        "LIVE_RUNTIME_AUTHORITY_INCONSISTENT",
        "LIVE_RUNTIME_AUTHORITY_UNKNOWN",
    }
    assert result["reason"] == "TEST_PENDING_AUTHORITY_STOP"
    assert manager.lifecycle_state == "RUNNING"
    assert manager.loop_state == "STOPPED"
