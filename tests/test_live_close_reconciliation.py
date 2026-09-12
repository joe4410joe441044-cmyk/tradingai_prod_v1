"""Focused normal LIVE close reconciliation tests (all exchange calls mocked)."""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Bot.engine.execution_engine import ExecutionEngine
from backend.runtime.runtime_health_snapshot import build_trading_decision_snapshot


def position(*, found, quantity=0, success=True, error_code=None, timestamp=None):
    signed = quantity if found else 0
    return {
        "success": success,
        "found": found,
        "quantity": abs(quantity),
        "signed_quantity": signed,
        "error_code": error_code,
        "timestamp": time.time() if timestamp is None else timestamp,
    }


def orders(count=0, *, success=True, timestamp=None):
    entries = [
        {"order_id": f"close-{index}", "reduceOnly": True}
        for index in range(count)
    ]
    return {
        "success": success,
        "count": count,
        "orders": entries,
        "timestamp": time.time() if timestamp is None else timestamp,
    }


def accepted(final_position, *, confirmed=False):
    return {
        "success": confirmed,
        "accepted": True,
        "confirmed": confirmed,
        "closed": confirmed,
        "skipped": False,
        "symbol": "ETHUSDTM",
        "order_id": "close-accepted-1",
        "raw_order": {"code": "200000"},
        "final_position": final_position,
        "error_code": None if confirmed else "POSITION_REMAINS",
    }


def live_engine(flatten, position_reads=(), order_reads=()):
    exchange = Mock()
    exchange.flatten_current_position.return_value = flatten
    exchange.get_current_position.side_effect = list(position_reads)
    exchange.get_open_orders.side_effect = list(order_reads)
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=SimpleNamespace(initial_balance=1000, balance=1000),
    )
    engine.mode = "live"
    engine.symbol = "ETHUSDT"
    engine.config.update({"mode": "live", "dry_run": False})
    engine.actual_position = {
        "side": "long", "qty": 10, "multiplier": 0.001,
        "entry_price": 100, "entry_time": time.time(),
        "order_id": "open-1", "trace_id": "trace-1",
    }
    engine.LIVE_CLOSE_RECONCILIATION_INTERVAL_SECONDS = 0
    engine.update_drawdown_state = lambda *args: {"riskTradingDisabled": False}
    return engine


def test_close_accepted_first_exchange_query_flat_confirms_after_orders_flat():
    engine = live_engine(accepted(position(found=False), confirmed=True),
                         order_reads=[orders()])

    result = engine.close_position(101, "TP")

    assert result["status"] == "CONFIRMED"
    assert result["reconciliationAttempts"] == 0
    assert result["positionState"] == result["openOrderState"] == "FLAT"
    assert engine.actual_position is None
    assert engine.pending_order is False
    engine.exchange.flatten_current_position.assert_called_once_with("ETHUSDT")
    engine.exchange.get_current_position.assert_not_called()


def test_nonflat_then_flat_reconciles_with_exactly_one_close_submission():
    engine = live_engine(
        accepted(position(found=True, quantity=10)),
        position_reads=[position(found=False)],
        order_reads=[orders()],
    )

    result = engine.close_position(101, "SL")

    assert result["confirmed"] is True
    assert result["reconciliationAttempts"] == 1
    assert engine.exchange.flatten_current_position.call_count == 1
    assert engine.exchange.get_current_position.call_count == 1


def test_partial_position_is_polled_until_later_flat_without_resubmission():
    engine = live_engine(
        accepted(position(found=True, quantity=10)),
        position_reads=[position(found=True, quantity=4), position(found=False)],
        order_reads=[orders(), orders()],
    )

    result = engine.close_position(101, "SL")

    assert result["confirmed"] is True
    assert result["reconciliationAttempts"] == 2
    assert engine.exchange.flatten_current_position.call_count == 1


def test_position_remaining_after_bound_is_fail_closed():
    engine = live_engine(
        accepted(position(found=True, quantity=10)),
        position_reads=[position(found=True, quantity=10)] * 3,
        order_reads=[orders()] * 3,
    )

    result = engine.close_position(101, "SL")

    assert result["status"] == "RECONCILIATION_FAILED"
    assert result["reason"] == "EXCHANGE_CLOSE_PARTIAL"
    assert result["reconciliationAttempts"] == 3
    assert engine.actual_position is not None
    assert engine.pending_order is True
    assert engine.live_close_in_flight is True
    assert engine.exchange.flatten_current_position.call_count == 1


def test_position_query_timeout_is_fail_closed():
    timeout = position(found=False, success=False, error_code="TIMEOUT")
    engine = live_engine(
        accepted(timeout), position_reads=[timeout] * 3,
        order_reads=[orders()] * 3,
    )

    result = engine.close_position(101, "SL")

    assert result["status"] == "RECONCILIATION_FAILED"
    assert result["reason"] == "EXCHANGE_POSITION_UNKNOWN"
    assert engine.actual_position is not None


def test_position_query_auth_failure_is_fail_closed():
    auth = position(found=False, success=False, error_code="AUTH_ERROR")
    engine = live_engine(
        accepted(auth), position_reads=[auth] * 3,
        order_reads=[orders()] * 3,
    )

    result = engine.close_position(101, "SL")

    assert result["confirmed"] is False
    assert result["reason"] == "EXCHANGE_POSITION_UNKNOWN"
    assert engine.actual_position is not None


@pytest.mark.parametrize("bad_position", [
    {"success": True, "found": False},
    position(found=False, timestamp=lambda: None),
])
def test_unknown_position_shape_is_fail_closed(bad_position):
    if callable(bad_position.get("timestamp")):
        bad_position["timestamp"] = time.time() - 31
    engine = live_engine(
        accepted(bad_position), position_reads=[bad_position] * 3,
        order_reads=[orders()] * 3,
    )

    result = engine.close_position(101, "SL")

    assert result["confirmed"] is False
    assert result["positionState"] == "UNKNOWN"
    assert engine.actual_position is not None


def test_flat_position_with_unresolved_open_close_order_is_not_complete():
    remaining = orders(1)
    engine = live_engine(
        accepted(position(found=False), confirmed=True),
        position_reads=[position(found=False)] * 3,
        order_reads=[remaining] * 4,
    )

    result = engine.close_position(101, "TP")

    assert result["status"] == "RECONCILIATION_FAILED"
    assert result["reason"] == "OPEN_CLOSE_ORDER_REMAINS"
    assert engine.actual_position is not None
    assert engine.live_close_in_flight is True


def test_exchange_flat_precedes_local_flat_and_lifecycle_record():
    authoritative_flat = position(found=False)
    engine = live_engine(accepted(authoritative_flat, confirmed=True),
                         order_reads=[orders()])

    result = engine.close_position(101, "MICROSTRUCTURE_EXIT")

    assert result["positionAuthority"] is authoritative_flat
    assert result["positionState"] == "FLAT"
    assert result["openOrderState"] == "FLAT"
    assert engine.actual_position is None
    assert engine.trade_history[-1]["status"] == "CLOSED"
    assert engine.trade_history[-1]["estimatedPnlAuthoritative"] is False

    cycle = build_trading_decision_snapshot(
        running=True, mode="LIVE", market_ready=True, runtime_result={},
        pending_order=engine.pending_order,
        position_active=engine.actual_position is not None,
        position_state="FLAT", close_state=engine.live_close_state,
    )
    assert cycle["currentState"] == "POSITION CLOSED"
    assert cycle["currentStageIndex"] == 14
    assert cycle["currentActivity"] == "READY_FOR_NEXT_TRADE"


def test_local_flat_never_proves_nonflat_exchange_complete():
    nonflat = position(found=True, quantity=2)
    engine = live_engine(
        accepted(nonflat), position_reads=[nonflat] * 3,
        order_reads=[orders()] * 3,
    )
    engine.actual_position = None

    result = engine._reconcile_live_close("ETHUSDT", accepted(nonflat))

    assert result["confirmed"] is False
    assert result["positionState"] == "NON_FLAT"
    assert engine.actual_position is None
    engine.exchange.flatten_current_position.assert_not_called()


def test_reconciliation_polling_and_subsequent_exit_tick_never_resubmit_close():
    nonflat = position(found=True, quantity=10)
    engine = live_engine(
        accepted(nonflat), position_reads=[nonflat] * 3,
        order_reads=[orders()] * 3,
    )

    first = engine.close_position(101, "SL")
    second = engine.close_position(102, "SL")

    assert first == second
    assert engine.exchange.flatten_current_position.call_count == 1
    assert engine.exchange.get_current_position.call_count == 3
