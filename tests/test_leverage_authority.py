"""TR-OP-CONNECT-7: Authoritative Leverage Boundary (backend).

Covers:

    User Requested Leverage
        -> MM Maximum Leverage (active config)
        -> Effective Leverage
        -> START Validation
        -> Execution

The MM contract is BLOCK (not clamp): an over-limit or invalid requested
leverage rejects START with MAXIMUM_LEVERAGE.  If the MM authority is
unavailable or malformed, the resolution fails closed.  Leverage must never
amplify the MM-approved risk amount.
"""

from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from backend.bot_manager.bot_manager import BotManager
from backend.market.exchange_factory import ExchangeFactory
from backend.money_management.engine import evaluate_money_management
from backend.money_management.enums import (
    MoneyManagementProfile,
    RiskBlockReason,
    TradingMode,
)
from backend.money_management.leverage_authority import (
    resolve_effective_leverage,
)
from backend.money_management.models import (
    MoneyManagementConfig,
    MoneyManagementDecisionInput,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from Bot.engine.execution_engine import ExecutionEngine


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
    manager.production_ams_mm_config_provider = None
    manager.money_management_config_provider = None
    for name, value in attrs.items():
        setattr(manager, name, value)
    return manager


# =========================
# A. requested < maximum
# =========================

def test_requested_below_maximum_yields_requested():
    result = resolve_effective_leverage(D("3"), D("5"))
    assert result.allowed is True
    assert result.effective_leverage == D("3")
    assert result.maximum_leverage == D("5")
    assert result.block_reason is RiskBlockReason.NONE


# =========================
# B. requested == maximum
# =========================

def test_requested_equals_maximum_yields_requested():
    result = resolve_effective_leverage(D("5"), D("5"))
    assert result.allowed is True
    assert result.effective_leverage == D("5")
    assert result.maximum_leverage == D("5")


# =========================
# C. requested > maximum  -> BLOCK (MM contract), not clamp
# =========================

def test_requested_above_maximum_is_blocked():
    result = resolve_effective_leverage(D("10"), D("5"))
    assert result.allowed is False
    assert result.effective_leverage is None
    assert result.maximum_leverage == D("5")
    assert result.block_reason is RiskBlockReason.MAXIMUM_LEVERAGE


@pytest.mark.parametrize("requested", ["5.0001", "6", "100"])
def test_requested_above_maximum_is_blocked_across_values(requested):
    result = resolve_effective_leverage(D(requested), D("5"))
    assert result.allowed is False
    assert result.block_reason is RiskBlockReason.MAXIMUM_LEVERAGE


# =========================
# D. MM authority unavailable -> fail closed
# =========================

@pytest.mark.parametrize("maximum", [None, "", 0, -1, "abc", float("inf"), float("nan")])
def test_authority_unavailable_fails_closed(maximum):
    result = resolve_effective_leverage(D("3"), maximum)
    assert result.allowed is False
    assert result.effective_leverage is None
    assert result.block_reason is RiskBlockReason.INSUFFICIENT_DATA


def test_authority_unavailable_never_uses_requested_as_authority():
    result = resolve_effective_leverage(D("3"), None)
    assert result.allowed is False
    assert result.effective_leverage is None


def test_status_projection_uses_the_same_allowed_resolution():
    manager = _bare_manager()
    manager._last_requested_leverage = 3
    manager._last_leverage_authority = resolve_effective_leverage(D("3"), D("5"))
    assert manager._leverage_authority_projection() == {
        "requestedLeverage": 3,
        "maximumLeverage": 5.0,
        "effectiveLeverage": 3.0,
        "allowed": True,
        "reason": "NONE",
    }


def test_status_projection_keeps_blocked_effective_unavailable():
    manager = _bare_manager()
    manager._last_requested_leverage = 10
    manager._last_leverage_authority = resolve_effective_leverage(D("10"), D("5"))
    projection = manager._leverage_authority_projection()
    assert projection["requestedLeverage"] == 10
    assert projection["maximumLeverage"] == 5.0
    assert projection["effectiveLeverage"] is None
    assert projection["allowed"] is False
    assert projection["reason"] == "MAXIMUM_LEVERAGE"


def test_status_projection_is_unavailable_before_any_start_resolution():
    manager = _bare_manager()
    projection = manager._leverage_authority_projection()
    assert projection["maximumLeverage"] is None
    assert projection["effectiveLeverage"] is None
    assert projection["allowed"] is None


# =========================
# E. malformed maximum leverage -> fail closed
# =========================

def test_malformed_maximum_leverage_is_fail_closed():
    result = resolve_effective_leverage(D("3"), "not-a-number")
    assert result.allowed is False
    assert result.block_reason is RiskBlockReason.INSUFFICIENT_DATA


def test_boolean_maximum_leverage_is_fail_closed():
    result = resolve_effective_leverage(D("3"), True)
    assert result.allowed is False
    assert result.block_reason is RiskBlockReason.INSUFFICIENT_DATA


# =========================
# F. negative / zero / non-finite requested leverage -> reject
# =========================

@pytest.mark.parametrize("requested", [D("0"), D("-1"), None, float("inf"), float("nan")])
def test_invalid_requested_leverage_is_rejected(requested):
    result = resolve_effective_leverage(requested, D("5"))
    assert result.allowed is False
    assert result.block_reason is RiskBlockReason.MAXIMUM_LEVERAGE


# =========================
# G. risk amount independence across 1x / 3x / 5x
# =========================

def _mm_decision_input(requested_leverage):
    return MoneyManagementDecisionInput(
        request_id="tr8-g",
        evaluated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        symbol="XRPUSDTM",
        requested_size=D("1000"),
        requested_notional=D("1000"),
        entry_price=D("100"),
        stop_loss_price=D("99"),
        account_equity=D("1000"),
        eligible_equity=D("1000"),
        governance_allowed=True,
        side="BUY",
        requested_leverage=requested_leverage,
    )


def test_mm_approved_risk_amount_is_not_amplified_by_leverage():
    cfg = _mm_config(D("5"))
    outcomes = [
        evaluate_money_management(_mm_decision_input(D(level)), cfg)
        for level in ("1", "3", "5")
    ]
    assert all(outcome.risk_allowed for outcome in outcomes)
    assert len({outcome.risk_amount for outcome in outcomes}) == 1
    assert outcomes[0].risk_amount == D("5")
    assert len({outcome.approved_notional for outcome in outcomes}) == 1
    assert outcomes[0].approved_notional == D("100")


def test_execution_leverage_only_changes_margin_not_notional_or_risk():
    """Execution treats leverage as margin-only, matching MM D06."""
    def preview_for(leverage):
        class PriceManager:
            def get_current_price(self):
                return 100.0
        engine = ExecutionEngine(
            exchange=None,
            portfolio=PortfolioManager(1000.0),
            price_manager=PriceManager(),
        )
        engine.symbol = "BTCUSDT"
        engine.set_config({
            "mode": "paper",
            "dry_run": True,
            "risk_percent": 0.5,
            "position_size": 0,
            "leverage": leverage,
        })
        engine.start()
        return engine.get_result()

    results = {level: preview_for(level) for level in (1, 3, 5)}
    for level in (1, 3, 5):
        preview = results[level]["preview"]
        assert preview["valid"] is True
        assert preview["sizing_mode"] == "risk_percent"
    # risk dollar amount = balance * risk_percent / 100, identical at every leverage.
    assert results[1]["risk_percent"] == 0.5
    assert results[3]["risk_percent"] == 0.5
    assert results[5]["risk_percent"] == 0.5
    assert results[1]["preview"]["required_margin"] == 5.0
    assert results[3]["preview"]["required_margin"] == pytest.approx(5.0 / 3.0)
    assert results[5]["preview"]["required_margin"] == 1.0
    # Position notional and quantity do not scale with leverage.
    assert results[1]["preview"]["position_size"] == 5.0
    assert results[3]["preview"]["position_size"] == 5.0
    assert results[5]["preview"]["position_size"] == 5.0
    assert results[1]["preview"]["qty"] == results[3]["preview"]["qty"]
    assert results[3]["preview"]["qty"] == results[5]["preview"]["qty"]


def test_execution_preserves_valid_fractional_effective_leverage():
    engine = ExecutionEngine(
        exchange=None,
        portfolio=PortfolioManager(1000.0),
        price_manager=None,
    )
    engine.set_config({"leverage": 2.5})
    assert engine.config["leverage"] == 2.5


# =========================
# H. START transport: validated effective leverage reaches downstream
# =========================

def test_bot_manager_resolve_leverage_authority_reads_active_mm_config():
    manager = _bare_manager(
        money_management_config_provider=lambda: _mm_config(D("5")),
    )
    result = manager._resolve_leverage_authority({"leverage": 4.0})
    assert result.allowed is True
    assert result.effective_leverage == D("4")
    assert result.maximum_leverage == D("5")


def test_bot_manager_resolve_leverage_authority_fails_closed_without_provider():
    manager = _bare_manager()
    result = manager._resolve_leverage_authority({"leverage": 3.0})
    assert result.allowed is False
    assert result.block_reason is RiskBlockReason.INSUFFICIENT_DATA


def test_start_rejects_over_limit_leverage_at_start_boundary():
    manager = _bare_manager(
        money_management_config_provider=lambda: _mm_config(D("5")),
    )
    result = manager.start({"leverage": 10, "mode": "paper"})
    assert result["status"] == "error"
    assert result["reason"] == "MAXIMUM_LEVERAGE"
    assert result["success"] is False
    assert result["completed"] is False


def test_start_fails_closed_when_mm_authority_unavailable():
    manager = _bare_manager()
    result = manager.start({"leverage": 3, "mode": "paper"})
    assert result["status"] == "error"
    assert result["reason"] == "INSUFFICIENT_DATA"
    assert result["success"] is False


def test_start_transports_effective_leverage_to_execution_engine():
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
        lambda: _mm_config(D("5")),
    )
    ws = Mock()
    ws.connected = False
    ws.start = Mock()
    config = {
        "symbol": "XRPUSDT",
        "exchange": "kucoin",
        "mode": "paper",
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 5,
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
        assert manager.engine.config["leverage"] == 4
        assert manager.config["effective_leverage"] == 4.0
        assert manager.config["maximum_leverage"] == 5.0
    finally:
        positions_router.set_engine(previous_positions_engine)
        if execution_runtime is not None:
            execution_runtime.set_engine(previous_runtime_engine)


# =========================
# Max-drawdown START canonical authority
# =========================


def _dd_config(drawdown=D("5")):
    return replace(_mm_config(), maximum_drawdown_pct=drawdown)


def test_bot_manager_resolve_max_drawdown_accepts_default_match():
    manager = _bare_manager(
        money_management_config_provider=lambda: _dd_config(D("5")),
    )
    assert manager._resolve_max_drawdown_authority({"max_drawdown_pct": 5.0}) == D("5")


def test_bot_manager_resolve_max_drawdown_accepts_nondefault_match():
    manager = _bare_manager(
        money_management_config_provider=lambda: _dd_config(D("7")),
    )
    assert manager._resolve_max_drawdown_authority({"max_drawdown_pct": 7.0}) == D("7")


def test_bot_manager_resolve_max_drawdown_rejects_mismatch():
    manager = _bare_manager(
        money_management_config_provider=lambda: _dd_config(D("7")),
    )
    with pytest.raises(ValueError) as exc:
        manager._resolve_max_drawdown_authority({"max_drawdown_pct": 5.0})
    assert "MAX_DRAWDOWN_PAYLOAD_MISMATCH_CANONICAL" in str(exc.value)


def test_bot_manager_resolve_max_drawdown_fail_closed_when_unavailable():
    manager = _bare_manager()
    with pytest.raises(ValueError) as exc:
        manager._resolve_max_drawdown_authority({"max_drawdown_pct": 5.0})
    assert "MAX_DRAWDOWN_UNAVAILABLE" in str(exc.value)


def test_bot_manager_max_drawdown_authority_projection_reads_base_config():
    manager = _bare_manager(
        money_management_config_provider=lambda: _dd_config(D("7")),
    )
    projection = manager._max_drawdown_authority_projection()
    assert projection["available"] is True
    assert projection["maximumDrawdownPercent"] == 7.0
    assert projection["reason"] is None


def test_bot_manager_max_drawdown_authority_projection_unavailable():
    manager = _bare_manager()
    projection = manager._max_drawdown_authority_projection()
    assert projection["available"] is False
    assert projection["maximumDrawdownPercent"] is None
    assert projection["reason"] == "MONEY_MANAGEMENT_MAX_DRAWDOWN_UNAVAILABLE"
