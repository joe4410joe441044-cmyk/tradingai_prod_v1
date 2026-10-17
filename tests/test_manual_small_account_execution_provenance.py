"""D-LIVE-14A: Small Account sizing provenance through final engine validation.

Offline regression only. The exchange adapter is a real ``KucoinTradeClient``
with its HTTP session mocked, so the exact wire quantity and the final
pre-exchange sizing revalidation are exercised without any real order.
"""

import json
import os
import time
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("TEST_MODE", "1")

from backend import config as backend_config
from backend.execution.kucoin_trade import KucoinTradeClient
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.money_management.order_sizing import SizingRejected
from backend.runtime.governance_runtime import governance_state

from sizing_support import account, contract_rules
from test_manual_trade_live_contract import (
    EXCHANGE_SYMBOL,
    SYMBOL,
    PriceManager,
    _build_live_manager,
    _trade,
)


EQUITY = D("7.91836966")
PRICE = D("1.39938")
TOLERANCE = D("0.00000001")


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


def _small_account_manager():
    client = KucoinTradeClient(
        api_key="fake",
        api_secret="fake",
        passphrase="fake",
    )
    client.set_live_order_gate(True, [])
    client.get_price = lambda symbol: float(PRICE)
    client.get_balance = lambda: float(EQUITY)
    client.get_positions = lambda symbol: {
        "symbol": EXCHANGE_SYMBOL,
        "qty": 10,
        "side": "BUY",
        "entry_price": float(PRICE),
    }
    client.get_margin_mode = lambda symbol, timeout=10: {
        "symbol": EXCHANGE_SYMBOL,
        "marginMode": "ISOLATED",
        "available": True,
        "source": "KUCOIN_V2_POSITION_MARGIN_MODE",
        "reason": None,
        "updatedAt": time.time(),
    }
    captured = []

    def post(url, **kwargs):
        captured.append(json.loads(kwargs["data"]))
        return SimpleNamespace(
            json=lambda: {"code": "200000", "data": {"orderId": "mock"}}
        )

    client.session.post = post

    manager, engine, exchange, recorder = _build_live_manager(client)
    engine.config.update({
        "position_size": 0,
        "leverage": 3,
        "effective_leverage": 3,
        "risk_percent": 0.5,
        "sl_percent": 1,
        "tp_percent": 2,
    })
    engine.price_manager = PriceManager(float(PRICE))
    engine.sizing_policy_provider = small_account_policy
    engine._sizing_account_cache = None
    engine._sizing_contract_cache = None
    exchange.get_account_overview = lambda: account(float(EQUITY))
    exchange.get_symbol_rules = lambda symbol: contract_rules(symbol, 10)
    manager.configured_symbol = EXCHANGE_SYMBOL
    return manager, engine, client, captured, recorder


def _authority_context():
    return {
        "entryAuthority": "MANUAL",
        "configuredSymbol": EXCHANGE_SYMBOL,
        "loopEnabled": False,
        "positionFlat": True,
        "pendingKnown": True,
        "pending": False,
        "marginModeKnown": True,
        "actualMarginMode": "ISOLATED",
        "marginModeCompatible": True,
    }


def _engine_authority(engine, price=PRICE):
    return engine._order_sizing_authority(
        price=price,
        rules=contract_rules(EXCHANGE_SYMBOL, 10),
        fresh=True,
        authority_context=_authority_context(),
    )


@pytest.fixture(autouse=True)
def _live_env():
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_governance():
    previous = dict(governance_state)
    governance_state["execution_enabled"] = False
    governance_state["no_trade_zone"] = False
    governance_state["emergency_stop"] = False
    yield
    governance_state.clear()
    governance_state.update(previous)


def test_small_account_manual_entry_preserves_policy_to_final_validation():
    manager, engine, _client, captured, _recorder = _small_account_manager()

    preparation = manager.get_manual_trade_preparation()
    assert preparation["valid"] is True
    assert preparation["sizingPolicyMode"] == "SMALL_ACCOUNT_MINIMUM_CONTRACT"
    assert preparation["candidate"]["contracts"] == "1"
    assert D(str(preparation["candidateRiskUsdt"])) <= D("0.158")
    assert D(str(preparation["candidateRiskPercent"])) <= D("2.0")

    observed = []
    original = engine._validate_final_entry_quantity

    def spy(**kwargs):
        observed.append(kwargs.get("sizing_policy_mode"))
        return original(**kwargs)

    engine._validate_final_entry_quantity = spy

    result = _trade(manager, "BUY", "d-live-14a-provenance")

    assert result["success"] is True
    assert observed == ["SMALL_ACCOUNT_MINIMUM_CONTRACT"]
    assert len(captured) == 1
    assert captured[0]["size"] == "1"
    assert captured[0]["leverage"] == "3"
    assert captured[0]["marginMode"] == "ISOLATED"


def test_engine_final_revalidation_rejects_two_small_account_contracts():
    _manager, engine, _client, _captured, _recorder = _small_account_manager()
    engine._manual_sizing_authority_context = _authority_context()
    try:
        with pytest.raises(
            SizingRejected, match="SMALL_ACCOUNT_REQUIRES_EXCHANGE_MINIMUM"
        ):
            engine._validate_final_entry_quantity(
                symbol=EXCHANGE_SYMBOL,
                contracts=2,
                price=float(PRICE),
                rules=contract_rules(EXCHANGE_SYMBOL, 10),
                leverage=3,
                approved_base=20,
                side="BUY",
                trace_id="d-live-14a-two",
                sizing_policy_mode="SMALL_ACCOUNT_MINIMUM_CONTRACT",
            )
    finally:
        engine._manual_sizing_authority_context = None


def test_engine_final_revalidation_rejects_risk_over_small_account_cap():
    _manager, engine, _client, _captured, _recorder = _small_account_manager()
    authority = _engine_authority(engine, price=D("1.5836"))
    with pytest.raises(
        SizingRejected, match="SMALL_ACCOUNT_ABSOLUTE_RISK_EXCEEDED"
    ):
        authority.validate(
            1, sizing_policy_mode="SMALL_ACCOUNT_MINIMUM_CONTRACT"
        )


def test_engine_rejects_unknown_sizing_policy_mode():
    _manager, engine, _client, _captured, _recorder = _small_account_manager()
    authority = _engine_authority(engine)
    with pytest.raises(SizingRejected, match="SIZING_POLICY_MODE_UNKNOWN"):
        authority.validate(1, sizing_policy_mode="FORGED_SMALL_ACCOUNT")


def test_engine_keeps_normal_mm_policy_for_normal_candidate():
    _manager, engine, client, _captured, _recorder = _small_account_manager()
    client.get_account_overview = lambda: account(1000)
    engine._sizing_account_cache = None
    engine._manual_sizing_authority_context = _authority_context()
    try:
        authority = _engine_authority(engine)
        assert authority.size()["sizingPolicyMode"] == "NORMAL_MM"
        assert engine._validate_final_entry_quantity(
            symbol=EXCHANGE_SYMBOL,
            contracts=1,
            price=float(PRICE),
            rules=contract_rules(EXCHANGE_SYMBOL, 10),
            leverage=3,
            approved_base=10,
            side="BUY",
            trace_id="d-live-14a-normal",
            sizing_policy_mode="NORMAL_MM",
        ) is True
    finally:
        engine._manual_sizing_authority_context = None


@pytest.mark.parametrize("case,reason", [
    ("mode_off", "SMALL_ACCOUNT_MODE_OFF"),
    ("cross_margin", "SMALL_ACCOUNT_REQUIRES_ISOLATED"),
    ("leverage", "SMALL_ACCOUNT_LEVERAGE_EXCEEDED"),
    ("pending", "SMALL_ACCOUNT_PENDING_UNSAFE"),
    ("position", "SMALL_ACCOUNT_REQUIRES_FLAT"),
    ("percent_risk", "SMALL_ACCOUNT_RISK_PERCENT_EXCEEDED"),
    ("absolute_risk", "SMALL_ACCOUNT_ABSOLUTE_RISK_EXCEEDED"),
])
def test_small_account_engine_authority_fails_closed(case, reason):
    _manager, engine, _client, _captured, _recorder = _small_account_manager()
    context = _authority_context()
    price = PRICE

    if case == "mode_off":
        engine.sizing_policy_provider = build_default_money_management_config
    elif case == "cross_margin":
        context["actualMarginMode"] = "CROSS"
    elif case == "leverage":
        engine.config["leverage"] = 4
        engine.config["effective_leverage"] = 4
    elif case == "pending":
        context["pending"] = True
    elif case == "position":
        context["positionFlat"] = False
    elif case == "percent_risk":
        engine.sizing_policy_provider = lambda: replace(
            small_account_policy(),
            small_account_max_risk_percent=D("1"),
        )
    elif case == "absolute_risk":
        price = D("1.5836")

    authority = engine._order_sizing_authority(
        price=price,
        rules=contract_rules(EXCHANGE_SYMBOL, 10),
        fresh=True,
        authority_context=context,
    )
    with pytest.raises(SizingRejected, match=reason):
        authority.validate(
            1, sizing_policy_mode="SMALL_ACCOUNT_MINIMUM_CONTRACT"
        )


def test_small_account_requires_matching_symbol_and_manual_authority():
    _manager, engine, _client, _captured, _recorder = _small_account_manager()
    wrong_symbol = dict(_authority_context(), configuredSymbol="ETHUSDTM")
    authority = engine._order_sizing_authority(
        price=PRICE,
        rules=contract_rules(EXCHANGE_SYMBOL, 10),
        fresh=True,
        authority_context=wrong_symbol,
    )
    with pytest.raises(SizingRejected, match="SMALL_ACCOUNT_SYMBOL_MISMATCH"):
        authority.validate(
            1, sizing_policy_mode="SMALL_ACCOUNT_MINIMUM_CONTRACT"
        )

    bot_authority = dict(_authority_context(), entryAuthority="BOT")
    authority = engine._order_sizing_authority(
        price=PRICE,
        rules=contract_rules(EXCHANGE_SYMBOL, 10),
        fresh=True,
        authority_context=bot_authority,
    )
    with pytest.raises(SizingRejected, match="SMALL_ACCOUNT_REQUIRES_MANUAL"):
        authority.validate(
            1, sizing_policy_mode="SMALL_ACCOUNT_MINIMUM_CONTRACT"
        )
