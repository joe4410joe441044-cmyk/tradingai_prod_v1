"""D-LIVE-4C-M1: KuCoin margin mode authority / fail-closed preflight.

The LIVE KuCoin entry payload requests ``marginMode="ISOLATED"`` while the
exchange symbol may currently be ``CROSS``.  These tests pin the repaired
contract:

    authoritative GET /api/v2/position/getMarginMode
        -> compare with requested ISOLATED
        -> equal: submit
        -> mismatch or authority unavailable: block before POST /api/v1/orders

The repair must never mutate the exchange margin mode and must never silently
change the requested mode to follow the exchange.
"""

import json
import time
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
import requests

from backend import config as backend_config
from backend.execution.kucoin_trade import (
    KucoinTradeClient,
    MARGIN_MODE_AUTHORITY_ENDPOINT,
    MARGIN_MODE_SOURCE,
    REQUESTED_MARGIN_MODE,
)
from backend.money_management.order_sizing import OrderSizingAuthority
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.governance_runtime import governance_state
from Bot.engine.execution_engine import ExecutionEngine
from sizing_support import install_sizing

EXCHANGE_SYMBOL = "XRPUSDTM"
SYMBOL = "XRPUSDT"


@pytest.fixture(autouse=True)
def _restore_governance_state():
    """Isolate the global governance/control authority mutated by the MANUAL path."""
    previous = dict(governance_state)
    yield
    governance_state.clear()
    governance_state.update(previous)


class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


def _sizing_validator(**final):
    authority = OrderSizingAuthority(
        symbol=final['symbol'], price=final['price'], equity=10000, available=10000,
        risk_percent=.5, sl_percent=1, leverage=final['leverage'], fixed_notional=0,
        position_cap=1000, symbol_capacity=1000, total_capacity=2000,
        multiplier=final['rules']['multiplier'], minimum=final['rules']['min_size'],
        step=final['rules'].get('qty_step', final['rules']['min_size']), maximum=1000000)
    authority.validate(final['contracts'])
    return True


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
        "qty_step": 1,
    }
    client.get_price = lambda symbol: 100.0
    return client


def _install_margin(monkeypatch, client, margin_mode="ISOLATED",
                    status_code=200, raises=None, data=None):
    """Install a GET stub that serves the v2 getMarginMode response."""
    calls = {"gets": 0, "urls": []}

    if data is None:
        data = {
            "code": "200000",
            "data": {"symbol": EXCHANGE_SYMBOL, "marginMode": margin_mode},
        }

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls["gets"] += 1
        calls["urls"].append(url)
        if raises is not None:
            raise raises
        return _FakeResponse(data, status_code)

    monkeypatch.setattr(client.session, "get", fake_get)
    return calls


def _capture_post(monkeypatch, client):
    captured = {"bodies": [], "posts": 0, "urls": []}

    def fake_post(url, headers=None, data=None, **kwargs):
        captured["posts"] += 1
        captured["urls"].append(url)
        captured["bodies"].append(json.loads(data))
        return _FakeResponse(
            {"code": "200000", "data": {"orderId": "order-1"}}
        )

    monkeypatch.setattr(client.session, "post", fake_post)
    return captured


def _entry(client, captured, symbol=SYMBOL, side="BUY", qty=1):
    return client.place_order(
        symbol=symbol,
        side=side,
        qty=qty,
        leverage=5,
        sizing_validator=_sizing_validator,
    )


# =========================
# TEST 1: exchange ISOLATED -> gate PASS -> submit
# =========================

def test_matching_isolated_exchange_margin_mode_allows_entry(monkeypatch):
    client = _live_client()
    _install_margin(monkeypatch, client, margin_mode="ISOLATED")
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is True
    assert captured["posts"] == 1
    assert captured["bodies"][0]["marginMode"] == "ISOLATED"


# =========================
# TEST 2: exchange CROSS vs requested ISOLATED -> mismatch, no POST
# =========================

def test_cross_exchange_margin_mode_blocks_entry_with_mismatch(monkeypatch):
    client = _live_client()
    _install_margin(monkeypatch, client, margin_mode="CROSS")
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is False
    assert result["blockedReason"] == "MARGIN_MODE_MISMATCH"
    assert result["error"] == "MARGIN_MODE_MISMATCH"
    assert result["requestedMarginMode"] == "ISOLATED"
    assert result["exchangeMarginMode"] == "CROSS"
    assert result["symbol"] == EXCHANGE_SYMBOL
    assert captured["posts"] == 0


# =========================
# TEST 3: authority read failure -> unavailable, no POST
# =========================

@pytest.mark.parametrize(
    "raises",
    [
        requests.exceptions.RequestException("boom"),
        requests.exceptions.Timeout("timeout"),
        RuntimeError("unexpected"),
    ],
)
def test_margin_mode_authority_unavailable_on_read_failure(monkeypatch, raises):
    client = _live_client()
    _install_margin(monkeypatch, client, raises=raises)
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is False
    assert result["blockedReason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


def test_margin_mode_authority_unavailable_on_http_error(monkeypatch):
    client = _live_client()
    _install_margin(monkeypatch, client, status_code=401)
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is False
    assert result["blockedReason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


def test_margin_mode_authority_unavailable_on_api_error_code(monkeypatch):
    client = _live_client()
    _install_margin(
        monkeypatch, client,
        data={"code": "400100", "data": None},
    )
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is False
    assert result["blockedReason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


# =========================
# TEST 4: response missing marginMode -> fail closed
# =========================

def test_missing_margin_mode_field_fails_closed(monkeypatch):
    client = _live_client()
    _install_margin(
        monkeypatch, client,
        data={"code": "200000", "data": {"symbol": EXCHANGE_SYMBOL}},
    )
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is False
    assert result["blockedReason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    assert result["exchangeMarginMode"] == "UNKNOWN"
    assert captured["posts"] == 0


# =========================
# TEST 5: unknown / unrecognized marginMode -> fail closed
# =========================

@pytest.mark.parametrize("value", ["HEDGE", "", None, 123, "isolated_x"])
def test_unknown_margin_mode_value_fails_closed(monkeypatch, value):
    client = _live_client()
    _install_margin(
        monkeypatch, client,
        data={"code": "200000", "data": {"symbol": EXCHANGE_SYMBOL, "marginMode": value}},
    )
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is False
    assert result["blockedReason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


# =========================
# TEST 6: reader uses GET getMarginMode, never changeMarginMode
# =========================

def test_reader_uses_get_margin_mode_endpoint_only(monkeypatch):
    client = _live_client()
    posts = {"count": 0, "urls": []}

    def fake_post(url, headers=None, data=None, **kwargs):
        posts["count"] += 1
        posts["urls"].append(url)
        return _FakeResponse({"code": "200000", "data": {}})

    monkeypatch.setattr(client.session, "post", fake_post)
    calls = _install_margin(monkeypatch, client, margin_mode="CROSS")

    authority = client.get_margin_mode(SYMBOL)

    assert authority["available"] is True
    assert authority["marginMode"] == "CROSS"
    assert calls["gets"] == 1
    assert calls["urls"][0] == (
        "https://api-futures.kucoin.com"
        + MARGIN_MODE_AUTHORITY_ENDPOINT
        + "?" + "symbol=" + EXCHANGE_SYMBOL
    )
    assert "changeMarginMode" not in calls["urls"][0]
    assert posts["count"] == 0


# =========================
# TEST 7: existing LIVE entry payload keeps marginMode ISOLATED
# =========================

def test_entry_payload_contract_still_uses_isolated(monkeypatch):
    client = _live_client()
    _install_margin(monkeypatch, client, margin_mode="ISOLATED")
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["success"] is True
    body = captured["bodies"][0]
    assert body["marginMode"] == "ISOLATED"
    assert body["type"] == "market"
    assert body["leverage"] == "5"


# =========================
# TEST 8: MANUAL LIVE cannot bypass the shared gate
# =========================

def _real_entry_client(monkeypatch, margin_mode="ISOLATED", margin_data=None,
                       margin_raises=None):
    client = _live_client()
    client.get_positions = lambda symbol=None: None
    client.get_balance = lambda: 1000.0
    client.get_open_orders = lambda *a, **k: {
        "success": True, "count": 0, "orders": [], "timestamp": time.time(),
    }
    _install_margin(
        monkeypatch, client,
        margin_mode=margin_mode, data=margin_data, raises=margin_raises,
    )
    captured = _capture_post(monkeypatch, client)
    return client, captured


def test_manual_live_entry_cannot_bypass_gate(monkeypatch):
    from test_manual_trade_live_contract import _build_live_manager, _trade

    client, captured = _real_entry_client(monkeypatch, margin_mode="CROSS")
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ):
        manager, _engine, _exchange, _recorder = _build_live_manager(client)
        result = _trade(manager, "BUY", "manual-margin-mismatch")

    assert captured["posts"] == 0
    assert result.get("success") is not True


# =========================
# TEST 9: BOT LIVE cannot bypass the shared gate
# =========================

def _bot_live_engine(client):
    engine = ExecutionEngine(
        exchange=client,
        portfolio=PortfolioManager(1000.0),
    )
    engine.mode = "live"
    engine.symbol = SYMBOL
    install_sizing(engine)
    engine.config["leverage"] = 5
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
    engine.set_execution_authority_guard(
        lambda signal: {"allowed": True, "entryAuthority": "BOT"}
    )
    engine._live_order_allowed = lambda authority_context: True
    engine._evaluate_execution_entry_guard = lambda order: (True, None)
    return engine


def test_bot_live_entry_cannot_bypass_gate(monkeypatch):
    client, captured = _real_entry_client(monkeypatch, margin_mode="CROSS")
    engine = _bot_live_engine(client)

    engine.try_entry({"id": "bot-margin-mismatch", "side": "BUY", "qty": 1})

    assert captured["posts"] == 0
    assert engine.actual_position is None


def test_bot_live_entry_submits_when_margin_mode_matches(monkeypatch):
    client, captured = _real_entry_client(monkeypatch, margin_mode="ISOLATED")
    engine = _bot_live_engine(client)

    engine.try_entry({"id": "bot-margin-ok", "side": "BUY", "qty": 1})

    assert captured["posts"] == 1
    assert captured["bodies"][0]["marginMode"] == "ISOLATED"


# =========================
# TEST 10: PAPER path does not require KuCoin margin authority
# =========================

def test_paper_entry_does_not_require_margin_mode_authority(monkeypatch):
    exchange = Mock()
    exchange.get_symbol_rules.return_value = {"multiplier": 1, "min_size": 1, "qty_step": 1}
    exchange.place_order.return_value = {"success": True}
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=PortfolioManager(1000.0),
    )
    engine.mode = "paper"
    engine.symbol = SYMBOL
    install_sizing(engine)
    engine.config["leverage"] = 5
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
# TEST 11: account/status projection exposes authoritative margin mode
# =========================

def test_account_status_projection_exposes_authoritative_margin_mode(monkeypatch):
    from backend.bot_manager.bot_manager import BotManager, MARGIN_MODE_SOURCE as SRC

    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)

    client = Mock()
    client.get_account_overview.return_value = {
        "accountType": "KUCOIN_FUTURES",
        "permission": "READ_ONLY",
        "balance": 100.0,
        "equity": 100.0,
        "availableBalance": 100.0,
        "walletBalance": 100.0,
        "unrealizedPnl": 0.0,
        "marginRatio": 0.0,
    }
    client.get_realized_pnl_today.return_value = {
        "value": 0.0,
        "source": "KUCOIN_FUTURES_REALISED_PNL_LEDGER",
        "observedAt": "2026-09-08T12:00:00Z",
        "dayStart": "2026-09-08T00:00:00Z",
        "complete": True,
    }
    client.get_positions.return_value = []
    client.get_margin_mode.return_value = {
        "symbol": EXCHANGE_SYMBOL,
        "marginMode": "CROSS",
        "available": True,
        "source": MARGIN_MODE_SOURCE,
        "reason": None,
        "updatedAt": 1234.5,
    }

    bot = BotManager()
    bot.account_read_client = client
    bot.account_read_client_exchange = "kucoin"

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["marginMode"] == "CROSS"
    assert snapshot["marginModeSource"] == SRC
    assert snapshot["marginModeUpdatedAt"] == 1234.5

    flattened = bot._flatten_account_runtime_fields({"realAccount": snapshot}, {})
    assert flattened["realMarginMode"] == "CROSS"
    assert flattened["realMarginModeSource"] == SRC
    assert flattened["realMarginModeUpdatedAt"] == 1234.5


def test_account_status_projection_unknown_when_authority_unavailable(monkeypatch):
    from backend.bot_manager.bot_manager import BotManager

    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)

    client = Mock()
    client.get_account_overview.return_value = {
        "accountType": "KUCOIN_FUTURES",
        "permission": "READ_ONLY",
        "balance": 100.0,
        "equity": 100.0,
        "availableBalance": 100.0,
        "walletBalance": 100.0,
        "unrealizedPnl": 0.0,
        "marginRatio": 0.0,
    }
    client.get_realized_pnl_today.return_value = None
    client.get_positions.return_value = []
    client.get_margin_mode.return_value = {
        "symbol": EXCHANGE_SYMBOL,
        "marginMode": None,
        "available": False,
        "source": MARGIN_MODE_SOURCE,
        "reason": "MARGIN_MODE_AUTHORITY_REQUEST_FAILED",
        "updatedAt": None,
    }

    bot = BotManager()
    bot.account_read_client = client
    bot.account_read_client_exchange = "kucoin"

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["marginMode"] == "UNKNOWN"


# =========================
# TEST 12: CROSS never silently changes the requested mode to CROSS
# =========================

def test_cross_exchange_never_rewrites_requested_mode(monkeypatch):
    assert REQUESTED_MARGIN_MODE == "ISOLATED"
    assert MARGIN_MODE_SOURCE == "KUCOIN_V2_POSITION_MARGIN_MODE"

    client = _live_client()
    _install_margin(monkeypatch, client, margin_mode="CROSS")
    captured = _capture_post(monkeypatch, client)

    result = _entry(client, captured)

    assert result["requestedMarginMode"] == "ISOLATED"
    assert result["exchangeMarginMode"] == "CROSS"
    assert captured["posts"] == 0
    assert all(body.get("marginMode") != "CROSS" for body in captured["bodies"])


def test_gate_helper_normalizes_lowercase_exchange_mode(monkeypatch):
    client = _live_client()
    _install_margin(
        monkeypatch, client,
        data={"code": "200000", "data": {"symbol": EXCHANGE_SYMBOL, "marginMode": "isolated"}},
    )

    block = client.margin_mode_entry_gate(SYMBOL)

    assert block is None


# =========================
# D-LIVE-4D: CANONICAL AUTHORITY CONTRACT
# =========================

def test_authority_contract_compatible_isolated(monkeypatch):
    client = _live_client()
    _install_margin(monkeypatch, client, margin_mode="ISOLATED")

    authority = client.margin_mode_authority(SYMBOL)

    assert authority["known"] is True
    assert authority["requiredMode"] == "ISOLATED"
    assert authority["actualMode"] == "ISOLATED"
    assert authority["compatible"] is True
    assert authority["reason"] == "MARGIN_MODE_COMPATIBLE"


def test_authority_contract_mismatch_cross(monkeypatch):
    client = _live_client()
    _install_margin(monkeypatch, client, margin_mode="CROSS")

    authority = client.margin_mode_authority(SYMBOL)

    assert authority["known"] is True
    assert authority["requiredMode"] == "ISOLATED"
    assert authority["actualMode"] == "CROSS"
    assert authority["compatible"] is False
    assert authority["reason"] == "MARGIN_MODE_MISMATCH"


@pytest.mark.parametrize("raises", [requests.exceptions.Timeout("t")])
def test_authority_contract_unavailable(monkeypatch, raises):
    client = _live_client()
    _install_margin(monkeypatch, client, raises=raises)

    authority = client.margin_mode_authority(SYMBOL)

    assert authority["known"] is False
    assert authority["requiredMode"] == "ISOLATED"
    assert authority["actualMode"] == "UNKNOWN"
    assert authority["compatible"] is False
    assert authority["reason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"


def test_reader_normalizes_symbol_xrpusdt_to_xrpusdtm(monkeypatch):
    client = _live_client()
    calls = _install_margin(monkeypatch, client, margin_mode="ISOLATED")

    client.get_margin_mode("XRPUSDT")

    assert calls["urls"][0].endswith("?symbol=XRPUSDTM")


# =========================
# D-LIVE-4D: CLOSE PATH SAFETY
# =========================


def _close_client():
    return _live_client()


def _flat_current_position():
    return {
        "success": True,
        "found": False,
        "symbol": EXCHANGE_SYMBOL,
        "exchange_symbol": EXCHANGE_SYMBOL,
        "side": None,
        "quantity": 0.0,
        "signed_quantity": 0.0,
        "raw": None,
        "timestamp": time.time(),
    }


def _found_current_position(raw, side="long", qty=10):
    signed = float(qty) if side == "long" else -float(qty)
    return {
        "success": True,
        "found": True,
        "symbol": EXCHANGE_SYMBOL,
        "exchange_symbol": EXCHANGE_SYMBOL,
        "side": side,
        "quantity": float(qty),
        "signed_quantity": signed,
        "raw": raw,
        "timestamp": time.time(),
    }


def _install_position_sequence(monkeypatch, client, first, final=None):
    if final is None:
        final = _flat_current_position()
    calls = {"n": 0}

    def fake_get_current_position(symbol, timeout=10):
        calls["n"] += 1
        return dict(first) if calls["n"] == 1 else dict(final)

    monkeypatch.setattr(client, "get_current_position", fake_get_current_position)
    return calls


def _capture_close_post(monkeypatch, client):
    captured = {"bodies": [], "posts": 0}

    def fake_post(url, headers=None, data=None, **kwargs):
        captured["posts"] += 1
        captured["bodies"].append(json.loads(data))
        return _FakeResponse({"code": "200000", "data": {"orderId": "close-1"}})

    monkeypatch.setattr(client.session, "post", fake_post)
    return captured


def test_close_isolated_position_uses_isolated_reduce_only(monkeypatch):
    client = _close_client()
    _install_position_sequence(
        monkeypatch, client,
        _found_current_position({
            "symbol": EXCHANGE_SYMBOL, "currentQty": 10, "marginMode": "ISOLATED",
        }),
    )
    captured = _capture_close_post(monkeypatch, client)

    result = client.flatten_current_position(SYMBOL)

    assert result["success"] is True
    assert captured["posts"] == 1
    body = captured["bodies"][0]
    assert body["marginMode"] == "ISOLATED"
    assert body["reduceOnly"] is True
    assert body["size"] == "10"


def test_close_cross_position_uses_cross_reduce_only(monkeypatch):
    client = _close_client()
    _install_position_sequence(
        monkeypatch, client,
        _found_current_position({
            "symbol": EXCHANGE_SYMBOL, "currentQty": 10, "marginMode": "CROSS",
        }),
    )
    captured = _capture_close_post(monkeypatch, client)

    result = client.flatten_current_position(SYMBOL)

    assert result["success"] is True
    body = captured["bodies"][0]
    assert body["marginMode"] == "CROSS"
    assert body["reduceOnly"] is True


def test_close_uses_cross_mode_from_legacy_cross_flag(monkeypatch):
    client = _close_client()
    _install_position_sequence(
        monkeypatch, client,
        _found_current_position({
            "symbol": EXCHANGE_SYMBOL, "currentQty": 10, "crossMode": True,
        }),
    )
    captured = _capture_close_post(monkeypatch, client)

    client.flatten_current_position(SYMBOL)

    assert captured["bodies"][0]["marginMode"] == "CROSS"
    assert captured["bodies"][0]["reduceOnly"] is True


def test_close_falls_back_to_get_margin_mode_when_position_has_no_mode(monkeypatch):
    client = _close_client()
    _install_position_sequence(
        monkeypatch, client,
        _found_current_position({
            "symbol": EXCHANGE_SYMBOL, "currentQty": 10,
        }),
    )
    _install_margin(monkeypatch, client, margin_mode="CROSS")
    captured = _capture_close_post(monkeypatch, client)

    client.flatten_current_position(SYMBOL)

    assert captured["bodies"][0]["marginMode"] == "CROSS"


def test_close_already_flat_submits_no_order(monkeypatch):
    client = _close_client()
    _install_position_sequence(monkeypatch, client, _flat_current_position())
    captured = _capture_close_post(monkeypatch, client)

    result = client.flatten_current_position(SYMBOL)

    assert result["success"] is True
    assert result["skipped"] is True
    assert captured["posts"] == 0


def test_close_unknown_margin_mode_fails_closed_without_order(monkeypatch):
    client = _close_client()
    _install_position_sequence(
        monkeypatch, client,
        _found_current_position({
            "symbol": EXCHANGE_SYMBOL, "currentQty": 10,
        }),
    )
    _install_margin(monkeypatch, client, raises=requests.exceptions.Timeout("t"))
    captured = _capture_close_post(monkeypatch, client)

    result = client.flatten_current_position(SYMBOL)

    assert result["success"] is False
    assert result["error_code"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"
    assert captured["posts"] == 0


# =========================
# D-LIVE-4D: STATUS PROJECTION CONTRACT
# =========================


def _status_bot(monkeypatch, margin_authority):
    from backend.bot_manager.bot_manager import BotManager

    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)

    client = Mock()
    client.get_account_overview.return_value = {
        "accountType": "KUCOIN_FUTURES",
        "permission": "READ_ONLY",
        "balance": 100.0,
        "equity": 100.0,
        "availableBalance": 100.0,
        "walletBalance": 100.0,
        "unrealizedPnl": 0.0,
        "marginRatio": 0.0,
    }
    client.get_realized_pnl_today.return_value = None
    client.get_positions.return_value = []
    client.margin_mode_authority.return_value = margin_authority

    bot = BotManager()
    bot.account_read_client = client
    bot.account_read_client_exchange = "kucoin"
    return bot, client


def test_status_projection_mismatch_contract(monkeypatch):
    bot, _client = _status_bot(monkeypatch, {
        "known": True,
        "requiredMode": "ISOLATED",
        "actualMode": "CROSS",
        "compatible": False,
        "reason": "MARGIN_MODE_MISMATCH",
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 12.5,
    })

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["requiredMarginMode"] == "ISOLATED"
    assert snapshot["actualMarginMode"] == "CROSS"
    assert snapshot["marginModeKnown"] is True
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == "MARGIN_MODE_MISMATCH"

    flattened = bot._flatten_account_runtime_fields({"realAccount": snapshot}, {})
    assert flattened["realRequiredMarginMode"] == "ISOLATED"
    assert flattened["realActualMarginMode"] == "CROSS"
    assert flattened["realMarginModeKnown"] is True
    assert flattened["realMarginModeCompatible"] is False
    assert flattened["realMarginModeReason"] == "MARGIN_MODE_MISMATCH"


def test_status_projection_compatible_contract(monkeypatch):
    bot, _client = _status_bot(monkeypatch, {
        "known": True,
        "requiredMode": "ISOLATED",
        "actualMode": "ISOLATED",
        "compatible": True,
        "reason": "MARGIN_MODE_COMPATIBLE",
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 12.5,
    })

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["marginModeKnown"] is True
    assert snapshot["marginModeCompatible"] is True
    assert snapshot["marginModeReason"] == "MARGIN_MODE_COMPATIBLE"


def test_status_projection_unavailable_never_coerces_compatible(monkeypatch):
    bot, _client = _status_bot(monkeypatch, {
        "known": False,
        "requiredMode": "ISOLATED",
        "actualMode": "UNKNOWN",
        "compatible": False,
        "reason": "MARGIN_MODE_AUTHORITY_UNAVAILABLE",
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": None,
    })

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["actualMarginMode"] == "UNKNOWN"
    assert snapshot["marginModeKnown"] is False
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == "MARGIN_MODE_AUTHORITY_UNAVAILABLE"


# =========================
# D-LIVE-4D: MANUAL PREPARATION BLOCKER
# =========================


def test_manual_preparation_exposes_margin_mode_mismatch_blocker(monkeypatch):
    from test_manual_trade_live_contract import _build_live_manager

    manager, engine, _exchange, _rec = _build_live_manager()
    engine.get_result = lambda: {
        "preview": {"valid": True, "qty": 1, "position_size": 100},
    }
    engine.get_price = lambda: 100

    client = Mock()
    client.margin_mode_authority.return_value = {
        "known": True,
        "requiredMode": "ISOLATED",
        "actualMode": "CROSS",
        "compatible": False,
        "reason": "MARGIN_MODE_MISMATCH",
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    }
    manager.account_read_client = client

    prep = manager.get_manual_trade_preparation()

    assert prep["valid"] is False
    assert prep["firstBlocker"] == "MARGIN_MODE_MISMATCH"
    assert prep["requiredMarginMode"] == "ISOLATED"
    assert prep["actualMarginMode"] == "CROSS"
    assert prep["marginModeKnown"] is True
    assert prep["marginModeCompatible"] is False


def test_manual_preparation_passes_when_margin_mode_compatible(monkeypatch):
    from test_manual_trade_live_contract import _build_live_manager

    manager, engine, _exchange, _rec = _build_live_manager()
    engine.get_result = lambda: {
        "preview": {"valid": True, "qty": 1, "position_size": 100},
    }
    engine.get_price = lambda: 100

    client = Mock()
    client.margin_mode_authority.return_value = {
        "known": True,
        "requiredMode": "ISOLATED",
        "actualMode": "ISOLATED",
        "compatible": True,
        "reason": "MARGIN_MODE_COMPATIBLE",
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    }
    manager.account_read_client = client

    prep = manager.get_manual_trade_preparation()

    assert prep["valid"] is True
    assert prep["firstBlocker"] is None
    assert prep["marginModeCompatible"] is True


# =========================
# D-LIVE-4D: NO AUTO MODE CHANGE
# =========================

def test_no_auto_margin_mode_change_endpoint_in_client():
    import inspect

    from backend.execution import kucoin_trade

    source = inspect.getsource(kucoin_trade)
    assert "/position/changeMarginMode" not in source
    assert MARGIN_MODE_AUTHORITY_ENDPOINT == "/api/v2/position/getMarginMode"
    assert not hasattr(KucoinTradeClient, "change_margin_mode")
