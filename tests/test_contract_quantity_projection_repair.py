"""Contract quantity projection repair regressions.

The PAPER engine must derive its position contract count from the same
canonical symbol/contract metadata that Money Management uses for sizing.
A fixed fallback (``0.001``) fabricated ``qty=70000`` for an economic
``70 XRP`` position whose canonical contract count is ``7`` (multiplier 10).

These tests are offline: PAPER simulation only, no exchange call and no
runtime mutation.
"""

import os
import time
from dataclasses import replace
from decimal import Decimal as D

import pytest

os.environ.setdefault("TEST_MODE", "1")

from backend.market.kucoin_futures_public import to_kucoin_futures_symbol
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.runtime.current_position_view import (
    current_position,
    kucoin_position_observation,
)
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)
from test_manual_trade_paper_entry_close import (
    EXCHANGE_SYMBOL,
    SYMBOL,
    _build_manager,
    _trade,
)


CANONICAL_MULTIPLIER = 10.0
PRICE = 1.0
ECONOMIC_QUANTITY = 70.0


def contract_rules(symbol, *, multiplier=CANONICAL_MULTIPLIER):
    return {
        "symbol": to_kucoin_futures_symbol(symbol),
        "status": "Open",
        "isInverse": False,
        "settle_currency": "USDT",
        "quote_currency": "USDT",
        "multiplier": multiplier,
        "min_size": 1,
        "qty_step": 1,
        "max_size": 1000000,
        "max_leverage": 75,
        "taker_fee_rate": 0,
    }


def small_account_policy():
    return replace(
        build_default_money_management_config(),
        risk_per_trade_pct=D("0.5"),
        small_account_minimum_contract_mode=True,
        small_account_allowed_symbol=EXCHANGE_SYMBOL,
        small_account_max_contracts=D("1"),
        small_account_max_risk_percent=D("2.0"),
        small_account_max_absolute_risk_usdt=D("0.158"),
        small_account_max_leverage=D("3"),
    )


@pytest.fixture(autouse=True)
def _reset_governance():
    previous = dict(governance_state)
    governance_state["control_authority"] = "BOT"
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    yield
    governance_state.clear()
    governance_state.update(previous)


def _manager(*, multiplier=CANONICAL_MULTIPLIER, position_size=ECONOMIC_QUANTITY,
             contract_provider=None):
    manager, engine, portfolio, price_manager, recorder = _build_manager(
        price=PRICE, position_size=position_size
    )
    if contract_provider is None:
        contract_provider = lambda symbol: contract_rules(
            symbol, multiplier=multiplier
        )
    engine.sizing_contract_provider = contract_provider
    engine._sizing_contract_cache = None
    return manager, engine, portfolio, price_manager, recorder


def _paper_view(position, *, now):
    account = {
        "available": True,
        "positions": [position],
        "positionState": "OPEN",
        "lastUpdate": now,
        "unrealizedPnl": 0,
    }
    return current_position(
        account, "PAPER", now=now, symbol=SYMBOL, current_price=PRICE
    )


def test_paper_position_uses_canonical_contract_count_and_preserves_coin_qty():
    manager, engine, portfolio, _price, _recorder = _manager()
    result = _trade(manager, "BUY", "cq-entry-1")

    assert result["success"] is True
    assert result["quantityUnit"] == "coin"
    position = engine.actual_position
    assert position["coin_qty"] == pytest.approx(ECONOMIC_QUANTITY)
    assert position["qty"] == pytest.approx(ECONOMIC_QUANTITY / CANONICAL_MULTIPLIER)
    assert position["multiplier"] == pytest.approx(CANONICAL_MULTIPLIER)
    assert portfolio.positions[SYMBOL]["size"] == pytest.approx(
        ECONOMIC_QUANTITY
    )

    risk = engine.get_risk_state()
    assert risk["activePositionQty"] == pytest.approx(ECONOMIC_QUANTITY)
    assert risk["activePositionContractQty"] == pytest.approx(
        ECONOMIC_QUANTITY / CANONICAL_MULTIPLIER
    )

    now = time.time()
    view = _paper_view(position, now=now)
    assert view["coinQuantity"] == pytest.approx(ECONOMIC_QUANTITY)
    assert view["contractQuantity"] == pytest.approx(
        ECONOMIC_QUANTITY / CANONICAL_MULTIPLIER
    )
    assert view["quantity"] == pytest.approx(ECONOMIC_QUANTITY)
    assert view["quantityUnit"] == "coin"


def test_contract_count_is_derived_from_metadata_not_hard_coded():
    multiplier = 2.0
    manager, engine, _portfolio, _price, _recorder = _manager(
        multiplier=multiplier
    )
    result = _trade(manager, "BUY", "cq-entry-2")

    assert result["success"] is True
    position = engine.actual_position
    assert position["multiplier"] == pytest.approx(multiplier)
    assert position["coin_qty"] == pytest.approx(ECONOMIC_QUANTITY)
    assert position["qty"] == pytest.approx(ECONOMIC_QUANTITY / multiplier)


def test_manual_entry_and_close_keep_economic_coin_quantity():
    manager, engine, portfolio, price_manager, _recorder = _manager()
    entry = _trade(manager, "BUY", "cq-long-entry")
    assert entry["success"] is True
    approved = entry["approvedQuantity"]
    assert approved == pytest.approx(ECONOMIC_QUANTITY)
    assert engine.actual_position["coin_qty"] == pytest.approx(approved)

    price_manager.price = 1.1
    close = _trade(manager, "SELL", "cq-long-close")
    assert close["success"] is True
    assert close["operation"] == "CLOSE_LONG"
    assert close["quantity"] == pytest.approx(approved)
    assert engine.actual_position is None
    assert portfolio.positions == {}

    record = engine.trade_history[-1]
    assert record["qty"] == pytest.approx(approved)
    assert record["pnl"] == pytest.approx((1.1 - PRICE) * approved)


def test_small_account_policy_preserves_coin_and_contract_projection():
    manager, engine, portfolio, _price, _recorder = _manager(
        position_size=0.0
    )
    engine.config.update({
        "leverage": 3,
        "effective_leverage": 3,
        "risk_percent": 0.5,
    })
    engine.sizing_policy_provider = small_account_policy
    engine._sizing_contract_cache = None

    result = _trade(manager, "BUY", "cq-small-account")
    assert result["success"] is True
    approved = result["approvedQuantity"]
    position = engine.actual_position
    assert position["coin_qty"] == pytest.approx(approved)
    assert position["qty"] == pytest.approx(approved / CANONICAL_MULTIPLIER)
    assert position["multiplier"] == pytest.approx(CANONICAL_MULTIPLIER)
    assert portfolio.positions[SYMBOL]["size"] == pytest.approx(approved)


def test_paper_and_live_projection_share_contract_quantity_semantics():
    now = time.time()
    paper_position = {
        "side": "BUY",
        "qty": 7,
        "coin_qty": 70,
        "multiplier": 10,
        "entry_price": PRICE,
        "entry_time": now,
        "entry_authority": "MANUAL",
        "runtimeSymbolContext": {"symbol": SYMBOL},
    }
    paper_view = _paper_view(paper_position, now=now)

    observation = kucoin_position_observation([
        {
            "id": "live-1",
            "symbol": EXCHANGE_SYMBOL,
            "currentQty": 7,
            "avgEntryPrice": PRICE,
            "markPrice": PRICE,
        }
    ], now)
    live_view = current_position(
        {"authenticated": True, "lastSync": now},
        "LIVE",
        now=now,
        observation=observation,
        symbol=EXCHANGE_SYMBOL,
    )

    assert paper_view["contractQuantity"] == pytest.approx(7)
    assert live_view["contractQuantity"] == pytest.approx(7)
    assert paper_view["quantityUnit"] == "coin"
    assert live_view["quantityUnit"] == "contract"
    assert {
        "contractQuantity", "coinQuantity", "quantity", "quantityUnit",
    } <= set(paper_view)
    assert {
        "contractQuantity", "coinQuantity", "quantity", "quantityUnit",
    } <= set(live_view)


def test_missing_contract_metadata_fails_closed_without_fabrication():
    def missing_multiplier(symbol):
        rules = contract_rules(symbol)
        rules["multiplier"] = None
        return rules

    manager, engine, portfolio, _price, _recorder = _manager(
        contract_provider=missing_multiplier
    )
    result = _trade(manager, "BUY", "cq-missing-metadata")

    assert result.get("success") is not True
    assert engine.actual_position is None
    assert engine.paper_orders == []
    assert engine.paper_fills == []
    assert portfolio.positions == {}

    engine.sizing_contract_provider = None
    engine.exchange = None
    engine._sizing_contract_cache = None
    assert engine._paper_contract_multiplier() is None
