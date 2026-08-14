import time
from datetime import datetime, timezone
from unittest.mock import patch

from Bot.engine.execution_engine import ExecutionEngine
from backend.bot_manager.bot_manager import BotManager
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionOperation,
)
from backend.money_management.loss_execution_integration import (
    LossExecutionAdmissionReason,
    LossExecutionAdmissionResult,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.routers import positions
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.governance_runtime import governance_state


class PriceManager:
    def __init__(self, price):
        self.price = price

    def get_current_price(self):
        return self.price


def allow_entry(intent):
    operation = {
        "BUY": LossExecutionOperation.NEW_BUY,
        "SELL": LossExecutionOperation.NEW_SELL,
    }[intent.requested_side]
    return LossExecutionAdmissionResult(
        operation=operation,
        decision=LossExecutionEntryDecision.ALLOW,
        allowed=True,
        reason=LossExecutionAdmissionReason.ENTRY_ALLOWED,
        generated_at=datetime.now(timezone.utc),
        revision=1,
        sequence=1,
        accepted=True,
    )


def paper_engine(price=100.0):
    manager = PriceManager(price)
    portfolio = PortfolioManager(1000.0)
    engine = ExecutionEngine(
        exchange=None,
        portfolio=portfolio,
        price_manager=manager,
    )
    engine.symbol = "BTCUSDT"
    engine.set_config({
        "mode": "paper",
        "dry_run": True,
        "position_size": 100,
        "leverage": 5,
        "sl_percent": 1,
        "tp_percent": 2,
    })
    engine.set_execution_entry_guard(allow_entry)
    engine.start()
    engine.on_price(engine.symbol, price)
    return engine, manager, portfolio


def test_paper_buy_runtime_order_fill_close_account_history_and_dashboard():
    engine, price, portfolio = paper_engine()
    runtime = ExecutionRuntime()
    runtime.set_engine(engine)
    strategy = {
        "executionAllowed": True,
        "direction": "BUY",
        "edge": 0.9,
        "confidence": 0.9,
        "risk": 0.1,
    }
    previous = dict(governance_state)
    try:
        governance_state["execution_enabled"] = True
        governance_state["emergency_stop"] = False
        with patch("backend.runtime.ExecutionRuntime.config.ALLOW_LIVE", False), patch(
            "backend.runtime.ExecutionRuntime.config.TRADE_MODE", "paper"
        ):
            result = runtime.process_execution_runtime(
                strategy,
                governance_decision={
                    "allowed": True,
                    "reason": None,
                    "direction": "BUY",
                },
            )
    finally:
        governance_state.clear()
        governance_state.update(previous)

    assert result["handoffExecuted"] is True
    assert result["runtime"]["executionAllowed"] is True
    assert len(engine.paper_orders) == 1
    assert len(engine.paper_fills) == 1
    assert engine.paper_orders[0]["status"] == "FILLED"
    assert engine.paper_fills[0]["orderId"] == engine.paper_orders[0]["orderId"]
    assert engine.actual_position["side"] == "BUY"
    assert "BTCUSDT" in portfolio.positions

    # A +2% tick reaches the configured paper TP and closes the position.
    price.price = 102.0
    engine.on_price("BTCUSDT", 102.0)

    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert engine.pnl == 2.0
    assert engine.balance == 1002.0
    assert portfolio.balance == 1002.0
    assert portfolio.realized_pnl == 2.0
    assert engine.get_result()["equity"] == 1002.0
    assert len(engine.trade_history) == 1
    assert engine.trade_history[0]["pnl"] == 2.0
    assert engine.trade_history[0]["reason"] == "TP"

    # The same account values consumed by Dashboard and Money Management are
    # updated after the close; realized PnL is not double-counted in equity.
    bot = BotManager()
    bot.engine = engine
    bot.lifecycle_state = "RUNNING"
    account = bot._capture_account_snapshot()
    assert account["balance"] == 1002.0
    assert account["equity"] == 1002.0
    assert account["realizedPnl"] == 2.0
    assert account["unrealizedPnl"] == 0.0
    metrics = bot._observe_money_management_runtime_metrics(
        before={"realizedPnl": 0.0},
        event_type="TRADE_CLOSE",
        event_key="paper-audit-close-1",
    )
    assert float(metrics.balance) == 1002.0
    assert float(metrics.current_equity) == 1002.0
    assert float(metrics.realized_pnl) == 2.0
    assert metrics.position_count == 0

    positions.set_engine(engine)
    try:
        assert positions.get_positions()["positions"] == []
        assert positions.get_history() == engine.trade_history
    finally:
        positions.set_engine(None)


def test_paper_sell_signal_creates_short_order_and_fill():
    engine, _, _ = paper_engine()
    engine.submit_signal({"id": int(time.time() * 1000), "side": "SELL"})

    assert engine.actual_position["side"] == "SELL"
    assert engine.paper_orders[0]["side"] == "SELL"
    assert engine.paper_fills[0]["side"] == "SELL"


def test_paper_order_never_reaches_exchange_when_global_config_is_live():
    class ExchangeMustNotBeCalled:
        def get_symbol_rules(self, symbol):
            return {"multiplier": 0.001, "min_size": 1}

        def place_order(self, **order):
            raise AssertionError("paper order reached exchange")

    engine, _, portfolio = paper_engine()
    engine.exchange = ExchangeMustNotBeCalled()

    with patch("backend.utils.order.TRADE_MODE", "live"), patch(
        "backend.utils.order.ALLOW_LIVE", True
    ):
        engine.submit_signal({"id": int(time.time() * 1000), "side": "BUY"})

    assert engine.actual_position["side"] == "BUY"
    assert "BTCUSDT" in portfolio.positions
    assert len(engine.paper_orders) == 1
    assert len(engine.paper_fills) == 1


def test_trade_history_endpoint_never_reads_live_history():
    engine, _, _ = paper_engine()
    engine.mode = "live"
    engine.trade_history.append({"mode": "paper"})
    positions.set_engine(engine)
    try:
        assert positions.get_history() == []
    finally:
        positions.set_engine(None)
