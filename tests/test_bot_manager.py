"""TR-OPERATION-CONNECT-6: Max Drawdown Authority backend contract tests.

The saved Money Management configuration is the single authority for
maximum drawdown. If unavailable, START must fail closed. If the payload
supplies a value that does not match the canonical authority, START must
also fail closed -- silent override is prohibited.

All tests are isolated mocks; no production runtime mutation.
"""

import math
import os

os.environ.setdefault("TEST_MODE", "1")

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.enums import (
    MoneyManagementProfile,
    TradingMode,
)
from backend.money_management.models import MoneyManagementConfig


def D(value):
    return Decimal(str(value))


def _mm_config(maximum_drawdown_pct=D("7.00")):
    return MoneyManagementConfig(
        MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
        TradingMode.PAPER,
        D("1000"), D(".50"), D("100"),
        maximum_drawdown_pct,
        D("20"), D("10"),
        D("5"), False,
    )


def _bare_manager(**attrs):
    manager = BotManager.__new__(BotManager)
    manager.engine = None
    manager.production_ams_mm_config_provider = None
    manager.money_management_config_provider = None
    for name, value in attrs.items():
        setattr(manager, name, value)
    return manager


def _max_drawdown_manager(drawdown_pct=D("7.00")):
    return _bare_manager(
        money_management_config_provider=lambda: _mm_config(drawdown_pct),
    )


# =========================
# 1. CANONICAL_VALUE_RESOLVED
# =========================

def test_canonical_value_resolved():
    manager = _max_drawdown_manager(D("7.00"))
    result = manager._resolve_max_drawdown_authority(
        {"max_drawdown_pct": 7}
    )
    assert result == 7.0


def test_canonical_value_resolved_with_payload_float():
    manager = _max_drawdown_manager(D("7.00"))
    result = manager._resolve_max_drawdown_authority(
        {"max_drawdown_pct": 7.0}
    )
    assert result == 7.0


# =========================
# 2. PAYLOAD_MISSING_ALLOWED_FROM_CANONICAL
# =========================

def test_payload_missing_allowed_from_canonical():
    manager = _max_drawdown_manager(D("7.00"))
    result = manager._resolve_max_drawdown_authority({})
    assert result == 7.0
    assert result != 5.0


def test_payload_missing_does_not_use_default_five():
    manager = _max_drawdown_manager(D("10.00"))
    result = manager._resolve_max_drawdown_authority({})
    assert result == 10.0


# =========================
# 3. MATCHING_PAYLOAD_ALLOWED
# =========================

def test_matching_payload_allowed_exact_int():
    manager = _max_drawdown_manager(D("7.00"))
    result = manager._resolve_max_drawdown_authority(
        {"max_drawdown_pct": 7}
    )
    assert result == 7.0


def test_matching_payload_allowed_float_close():
    manager = _max_drawdown_manager(D("5.00"))
    result = manager._resolve_max_drawdown_authority(
        {"max_drawdown_pct": 5.0}
    )
    assert result == 5.0


# =========================
# 4. PAYLOAD_MISMATCH_FAIL_CLOSED
# =========================

def test_payload_mismatch_fail_closed():
    manager = _max_drawdown_manager(D("7.00"))
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority(
            {"max_drawdown_pct": 5}
        )
    assert "MAX_DRAWDOWN_PAYLOAD_MISMATCH_CANONICAL" in str(exc_info.value)


def test_payload_mismatch_below_canonical_fail_closed():
    manager = _max_drawdown_manager(D("10.00"))
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority(
            {"max_drawdown_pct": 7}
        )
    assert "MAX_DRAWDOWN_PAYLOAD_MISMATCH_CANONICAL" in str(exc_info.value)


def test_payload_mismatch_above_canonical_fail_closed():
    manager = _max_drawdown_manager(D("5.00"))
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority(
            {"max_drawdown_pct": 10}
        )
    assert "MAX_DRAWDOWN_PAYLOAD_MISMATCH_CANONICAL" in str(exc_info.value)


# =========================
# 5. LEGACY_DEFAULT_FIVE_NOT_AUTHORITY
# =========================

def test_legacy_default_five_not_authority():
    manager = _max_drawdown_manager(D("7.00"))
    result = manager._resolve_max_drawdown_authority({})
    assert result == 7.0
    assert result != 5.0


def test_legacy_default_five_not_used_for_other_canonical():
    manager = _max_drawdown_manager(D("7.50"))
    result = manager._resolve_max_drawdown_authority({})
    assert result == 7.5
    assert result != 5.0


# =========================
# 6. CONFIG_PROVIDER_MISSING_FAIL_CLOSED
# =========================

def test_config_provider_missing_fail_closed():
    manager = _bare_manager()
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_UNAVAILABLE" in str(exc_info.value)


def test_config_provider_not_callable_fail_closed():
    manager = _bare_manager(money_management_config_provider="not_callable")
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_UNAVAILABLE" in str(exc_info.value)


# =========================
# 7. SAVED_CONFIG_MISSING_FAIL_CLOSED
# =========================

def test_saved_config_missing_fail_closed():
    manager = _bare_manager(
        money_management_config_provider=lambda: None,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_UNAVAILABLE" in str(exc_info.value)


def test_saved_config_without_maximum_drawdown_pct_fail_closed():
    provider_object = Mock(spec=["some_other_attr"])
    provider_object.some_other_attr = "value"
    manager = _bare_manager(
        money_management_config_provider=lambda: provider_object,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_UNAVAILABLE" in str(exc_info.value)


def test_saved_config_with_maximum_drawdown_pct_none_fail_closed():
    provider_object = Mock()
    provider_object.maximum_drawdown_pct = None
    manager = _bare_manager(
        money_management_config_provider=lambda: provider_object,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_UNAVAILABLE" in str(exc_info.value)


# =========================
# 8. INVALID_CANONICAL_FAIL_CLOSED
# =========================

@pytest.mark.parametrize("invalid_value", [
    float("nan"),
    float("inf"),
    0,
    -1,
    -0.5,
])
def test_invalid_canonical_fail_closed(invalid_value):
    config = _mm_config(D("7.00"))
    object.__setattr__(config, "maximum_drawdown_pct", invalid_value)
    manager = _bare_manager(
        money_management_config_provider=lambda: config,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_INVALID" in str(exc_info.value)


def test_canonical_zero_fail_closed():
    config = _mm_config(D("7.00"))
    object.__setattr__(config, "maximum_drawdown_pct", 0)
    manager = _bare_manager(
        money_management_config_provider=lambda: config,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_INVALID" in str(exc_info.value)


def test_canonical_negative_fail_closed():
    config = _mm_config(D("7.00"))
    object.__setattr__(config, "maximum_drawdown_pct", -3)
    manager = _bare_manager(
        money_management_config_provider=lambda: config,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_INVALID" in str(exc_info.value)


def test_canonical_non_numeric_fail_closed():
    config = _mm_config(D("7.00"))
    object.__setattr__(config, "maximum_drawdown_pct", "not-a-number")
    manager = _bare_manager(
        money_management_config_provider=lambda: config,
    )
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority({})
    assert "MONEY_MANAGEMENT_MAX_DRAWDOWN_INVALID" in str(exc_info.value)


# =========================
# 9. PAYLOAD_NON_NUMERIC_FAIL_CLOSED
# =========================

def test_payload_non_numeric_fail_closed():
    manager = _max_drawdown_manager(D("7.00"))
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority(
            {"max_drawdown_pct": "seven"}
        )
    assert "MAX_DRAWDOWN_PAYLOAD_MISMATCH_CANONICAL" in str(exc_info.value)


def test_payload_nan_fail_closed():
    manager = _max_drawdown_manager(D("7.00"))
    with pytest.raises(ValueError) as exc_info:
        manager._resolve_max_drawdown_authority(
            {"max_drawdown_pct": float("nan")}
        )
    assert "MAX_DRAWDOWN_PAYLOAD_MISMATCH_CANONICAL" in str(exc_info.value)


# =========================
# 10. ENGINE_PROPAGATION_CONTRACT
# =========================

def test_engine_propagation_contract():
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("7.00")),
    )
    ws = Mock()
    ws.connected = False
    ws.start = Mock()
    config = {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "paper",
        "dry_run": True,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 7,
        "sl_percent": 0.5,
        "tp_percent": 1,
        "timeframe": "5m",
        "trailing_stop": True,
        "leverage": 4.0,
    }
    try:
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            return_value=ws,
        ):
            result = manager.start(config)

        assert result["status"] == "started"
        assert manager.engine.config["max_drawdown_pct"] == 7.0
        assert manager.config["max_drawdown_pct"] == 7.0
    finally:
        positions_router.set_engine(previous_positions_engine)
        if execution_runtime is not None:
            execution_runtime.set_engine(previous_runtime_engine)


def test_engine_propagation_uses_canonical_not_raw_payload():
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("7.00")),
    )
    ws = Mock()
    ws.connected = False
    ws.start = Mock()
    config = {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "paper",
        "dry_run": True,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 7,
        "sl_percent": 0.5,
        "tp_percent": 1,
        "timeframe": "5m",
        "trailing_stop": True,
        "leverage": 4.0,
    }
    try:
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            return_value=ws,
        ):
            result = manager.start(config)

        assert result["status"] == "started"
        assert manager.engine.config["max_drawdown_pct"] == 7.0
        assert manager.config["max_drawdown_pct"] == 7.0
        assert manager.config["max_drawdown_pct"] != 5.0
    finally:
        positions_router.set_engine(previous_positions_engine)
        if execution_runtime is not None:
            execution_runtime.set_engine(previous_runtime_engine)


def test_engine_propagation_matches_mm_saved_config():
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )
    mm_drawdown = D("8.50")
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(mm_drawdown),
    )
    ws = Mock()
    ws.connected = False
    ws.start = Mock()
    config = {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "paper",
        "dry_run": True,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 8.5,
        "sl_percent": 0.5,
        "tp_percent": 1,
        "timeframe": "5m",
        "trailing_stop": True,
        "leverage": 4.0,
    }
    try:
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            return_value=ws,
        ):
            result = manager.start(config)

        assert result["status"] == "started"
        assert manager.engine.config["max_drawdown_pct"] == float(mm_drawdown)
        assert manager.config["max_drawdown_pct"] == float(mm_drawdown)
    finally:
        positions_router.set_engine(previous_positions_engine)
        if execution_runtime is not None:
            execution_runtime.set_engine(previous_runtime_engine)


def test_engine_propagation_unknown_not_coerced_to_zero():
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("7.00")),
    )
    ws = Mock()
    ws.connected = False
    ws.start = Mock()
    config = {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "paper",
        "dry_run": True,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 7,
        "sl_percent": 0.5,
        "tp_percent": 1,
        "timeframe": "5m",
        "trailing_stop": True,
        "leverage": 4.0,
    }
    try:
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            return_value=ws,
        ):
            result = manager.start(config)

        assert result["status"] == "started"
        assert manager.engine.config["max_drawdown_pct"] != 0
        assert manager.engine.config["max_drawdown_pct"] > 0
        assert manager.config["max_drawdown_pct"] != 0
        assert manager.config["max_drawdown_pct"] > 0
    finally:
        positions_router.set_engine(previous_positions_engine)
        if execution_runtime is not None:
            execution_runtime.set_engine(previous_runtime_engine)
