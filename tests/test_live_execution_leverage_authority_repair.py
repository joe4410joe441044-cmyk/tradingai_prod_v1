"""TRADINGAI-LIVE-EXECUTION-LEVERAGE-AUTHORITY-REPAIR-1.

The LIVE Execution order construction path previously hard-coded
``"leverage": "10"`` on the KuCoin order payload, silently increasing the
reviewed effective leverage.  These tests pin the repaired contract:

    canonical effective leverage -> LIVE KuCoin order payload leverage

and prove that a missing / invalid authority fails closed instead of
falling back to a hard-coded value.  The reduceOnly close path does not
carry an order-level leverage authority at all.
"""

import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.execution.kucoin_trade import KucoinTradeClient
from backend.money_management.leverage_authority import (
    resolve_effective_leverage,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from Bot.engine.execution_engine import ExecutionEngine


class _FakeResponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _live_client():
    client = KucoinTradeClient(
        api_key="key",
        api_secret="secret",
        passphrase="passphrase",
    )
    client.set_live_order_gate(True, [])
    client.get_symbol_rules = lambda symbol: {
        "min_size": 1,
        "multiplier": 1.0,
    }
    client.get_price = lambda symbol: 100.0
    return client


def _capture_post(monkeypatch, client, response_data=None):
    captured = {"bodies": [], "posts": 0}
    payload = response_data or {
        "code": "200000",
        "data": {"orderId": "order-1"},
    }

    def fake_post(url, headers=None, data=None, **kwargs):
        captured["posts"] += 1
        captured["bodies"].append(json.loads(data))
        return _FakeResponse(payload)

    monkeypatch.setattr(client.session, "post", fake_post)
    return captured


# =========================
# A. reviewed 5x authority -> order leverage 5
# =========================

def test_live_order_uses_canonical_5x_authority(monkeypatch):
    client = _live_client()
    captured = _capture_post(monkeypatch, client)

    result = client.create_order(
        symbol="XRPUSDT",
        side="BUY",
        qty=1,
        leverage=5,
    )

    assert result["success"] is True
    assert captured["posts"] == 1
    assert captured["bodies"][0]["leverage"] == "5"


# =========================
# B. non-5 valid authority is used exactly (no hard-coded 5)
# =========================

@pytest.mark.parametrize(
    ("authority", "expected"),
    [
        (3, "3"),
        (Decimal("2.5"), "2.5"),
        ("4", "4"),
        (Decimal("5"), "5"),
    ],
)
def test_live_order_uses_exact_canonical_authority(
    monkeypatch, authority, expected
):
    client = _live_client()
    captured = _capture_post(monkeypatch, client)

    result = client.create_order(
        symbol="XRPUSDT",
        side="BUY",
        qty=1,
        leverage=authority,
    )

    assert result["success"] is True
    assert captured["bodies"][0]["leverage"] == expected


# =========================
# C. missing authority -> fail closed, no order
# =========================

def test_missing_leverage_authority_fails_closed(monkeypatch):
    client = _live_client()
    captured = _capture_post(monkeypatch, client)

    result = client.create_order(
        symbol="XRPUSDT",
        side="BUY",
        qty=1,
    )

    assert result["success"] is False
    assert result["error"] == "LEVERAGE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


# =========================
# D. invalid authority -> fail closed, no order
# =========================

@pytest.mark.parametrize(
    "authority",
    [None, "", "abc", 0, -1, 0.0, float("inf"), float("nan"), True],
)
def test_invalid_leverage_authority_fails_closed(monkeypatch, authority):
    client = _live_client()
    captured = _capture_post(monkeypatch, client)

    result = client.create_order(
        symbol="XRPUSDT",
        side="BUY",
        qty=1,
        leverage=authority,
    )

    assert result["success"] is False
    assert result["error"] == "LEVERAGE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


# =========================
# E. effective leverage is the authority used (not requested higher)
# =========================

def test_effective_leverage_below_requested_is_the_authority_used(
    monkeypatch,
):
    # The MM contract blocks requested > maximum, so the only permitted
    # effective leverage is <= maximum.  The adapter must construct the
    # order with that effective value, never the requested value.
    effective = resolve_effective_leverage(Decimal("3"), Decimal("5"))
    assert effective.allowed is True
    assert effective.effective_leverage == Decimal("3")

    client = _live_client()
    captured = _capture_post(monkeypatch, client)
    client.create_order(
        symbol="XRPUSDT",
        side="BUY",
        qty=1,
        leverage=effective.effective_leverage,
    )

    assert captured["bodies"][0]["leverage"] == "3"


def test_over_limit_requested_leverage_is_blocked_not_clamped():
    result = resolve_effective_leverage(Decimal("10"), Decimal("5"))
    assert result.allowed is False
    assert result.effective_leverage is None


# =========================
# F. no hidden 10x fallback
# =========================

def test_no_hidden_10x_fallback_when_authority_absent(monkeypatch):
    client = _live_client()
    captured = _capture_post(monkeypatch, client)

    client.create_order(symbol="XRPUSDT", side="BUY", qty=1)

    assert captured["posts"] == 0
    assert all(
        body.get("leverage") != "10" for body in captured["bodies"]
    )


# =========================
# G. PAPER remains simulation only
# =========================

def test_paper_entry_never_calls_exchange_order(monkeypatch):
    exchange = Mock()
    exchange.get_symbol_rules.return_value = {"multiplier": 1}
    exchange.place_order.return_value = {"success": True}
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=PortfolioManager(1000.0),
    )
    engine.mode = "paper"
    engine.symbol = "XRPUSDT"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = 100
    engine.config["dry_run"] = True
    engine.get_price = lambda: 100
    engine.get_result = lambda: {"preview": {"qty": 1, "valid": True}}
    engine.refresh_balance = lambda: None
    engine._evaluate_execution_entry_guard = lambda order: (True, None)

    engine.try_entry({"id": "paper-1", "side": "BUY", "qty": 1})

    exchange.place_order.assert_not_called()


# =========================
# H. close / reduceOnly path carries no order-level leverage
# =========================

def test_reduce_only_close_omits_leverage(monkeypatch):
    client = _live_client()
    captured = _capture_post(monkeypatch, client)

    initial = {
        "success": True,
        "found": True,
        "symbol": "XRPUSDTM",
        "exchange_symbol": "XRPUSDTM",
        "side": "long",
        "quantity": 3.0,
        "signed_quantity": 3.0,
        "raw_quantity": 3.0,
        "error_code": None,
        "error": None,
    }
    final = {
        "success": True,
        "found": False,
        "symbol": "XRPUSDTM",
        "exchange_symbol": "XRPUSDTM",
        "error_code": None,
        "error": None,
    }
    positions = iter([initial, final])
    monkeypatch.setattr(
        client, "get_current_position", lambda symbol, timeout=10: next(positions)
    )

    result = client.flatten_current_position("XRPUSDT")

    assert result["success"] is True
    assert result["accepted"] is True
    assert result["confirmed"] is True
    body = captured["bodies"][0]
    assert body["reduceOnly"] is True
    assert body["type"] == "market"
    assert "leverage" not in body


# =========================
# I. contract normalization / quantity behavior unchanged
# =========================

def test_entry_quantity_normalization_unchanged(monkeypatch):
    client = _live_client()
    client.get_symbol_rules = lambda symbol: {
        "min_size": 2,
        "multiplier": 2.0,
    }
    captured = _capture_post(monkeypatch, client)

    result = client.create_order(
        symbol="XRPUSDT",
        side="BUY",
        qty=6,
        leverage=5,
    )

    assert result["success"] is True
    body = captured["bodies"][0]
    assert body["size"] == "3"
    assert body["leverage"] == "5"
    assert body["type"] == "market"
    assert body["marginMode"] == "ISOLATED"


# =========================
# J. canonical authority reaches the LIVE order boundary
# =========================

def test_engine_live_entry_passes_canonical_effective_leverage():
    exchange = Mock()
    exchange.get_symbol_rules.return_value = {"multiplier": 1}
    exchange.place_order.return_value = {"success": True}
    exchange.get_positions.return_value = {
        "state": "OPEN",
        "side": "BUY",
        "qty": 1,
    }
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=PortfolioManager(1000.0),
    )
    engine.mode = "live"
    engine.symbol = "XRPUSDT"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = 100
    engine.config["dry_run"] = False
    engine.config["effective_leverage"] = 5
    engine.config["realOrderAllowed"] = True
    engine.config["executionEntryAllowed"] = True
    engine.config["liveOrderEntryAllowed"] = True
    engine.get_price = lambda: 100
    engine.get_result = lambda: {"preview": {"qty": 1, "valid": True}}
    engine.refresh_balance = lambda: None
    engine._live_order_allowed = lambda: True
    engine._evaluate_execution_entry_guard = lambda order: (True, None)

    engine.try_entry({"id": "live-1", "side": "BUY", "qty": 1})

    exchange.place_order.assert_called_once()
    assert exchange.place_order.call_args.kwargs["leverage"] == 5


def test_engine_live_entry_without_canonical_authority_passes_none():
    exchange = Mock()
    exchange.get_symbol_rules.return_value = {"multiplier": 1}
    exchange.place_order.return_value = {"success": True}
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=PortfolioManager(1000.0),
    )
    engine.mode = "live"
    engine.symbol = "XRPUSDT"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = 100
    engine.config["dry_run"] = False
    engine.config["realOrderAllowed"] = True
    engine.config["executionEntryAllowed"] = True
    engine.config["liveOrderEntryAllowed"] = True
    engine.get_price = lambda: 100
    engine.get_result = lambda: {"preview": {"qty": 1, "valid": True}}
    engine.refresh_balance = lambda: None
    engine._live_order_allowed = lambda: True
    engine._evaluate_execution_entry_guard = lambda order: (True, None)

    engine.try_entry({"id": "live-2", "side": "BUY", "qty": 1})

    exchange.place_order.assert_called_once()
    assert exchange.place_order.call_args.kwargs["leverage"] is None


def test_set_config_propagates_canonical_effective_leverage():
    engine = ExecutionEngine(
        exchange=None,
        portfolio=PortfolioManager(1000.0),
    )
    engine.set_config({"mode": "paper", "leverage": 5, "effective_leverage": 5})
    assert engine.config["effective_leverage"] == 5
    assert engine.config["leverage"] == 5
