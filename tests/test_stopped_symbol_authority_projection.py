"""D-LIVE-4F: STOPPED symbol authority / margin-mode projection.

Pins the D-LIVE-4F contract:

* a single read-only symbol resolver owns the diagnostic symbol used for the
  margin-mode projection;
* precedence is runtime symbol -> orderbook symbol -> last START config
  symbol -> unavailable;
* an absent symbol (None / blank / literal NONE / NULL / UNKNOWN) is never
  forwarded to an exchange request, so ``symbol=NONE`` can never reach KuCoin;
* no frontend default and no AUTO Market Selection candidate is used as a
  substitute for a missing MANUAL symbol authority;
* an unavailable symbol projects UNKNOWN / fail-closed and is never coerced to
  CROSS / compatible.

All tests are GET-only and mutate no runtime / exchange state.
"""

import time
from unittest.mock import Mock

import pytest
import requests

from backend.bot_manager.bot_manager import (
    BotManager,
    SYMBOL_AUTHORITY_RESOLVED,
    SYMBOL_AUTHORITY_UNAVAILABLE,
)
from backend.execution.kucoin_trade import (
    ABSENT_SYMBOL_VALUES,
    KucoinTradeClient,
    MARGIN_MODE_AUTHORITY_UNAVAILABLE,
    MARGIN_MODE_COMPATIBLE,
    MARGIN_MODE_MISMATCH,
    MARGIN_MODE_SOURCE,
    REQUESTED_MARGIN_MODE,
)

SYMBOL = "XRPUSDT"
EXCHANGE_SYMBOL = "XRPUSDTM"


class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


def _bot(**kwargs):
    bot = BotManager()
    for key, value in kwargs.items():
        setattr(bot, key, value)
    return bot


# =========================
# A: runtime symbol wins
# =========================

def test_runtime_symbol_wins():
    bot = _bot(
        _active_symbol=SYMBOL,
        orderbook_symbol=EXCHANGE_SYMBOL,
        config={"symbol": SYMBOL},
    )

    resolved = bot.resolve_read_only_symbol()

    assert resolved["known"] is True
    assert resolved["symbol"] == EXCHANGE_SYMBOL
    assert resolved["source"] == "ACTIVE_RUNTIME_SYMBOL"
    assert resolved["reason"] == SYMBOL_AUTHORITY_RESOLVED


# =========================
# B: config XRPUSDT -> XRPUSDTM
# =========================

def test_config_symbol_xrpusdt_resolves_exchange_symbol():
    bot = _bot(_active_symbol=None, orderbook_symbol=None, config={"symbol": "XRPUSDT"})

    resolved = bot.resolve_read_only_symbol()

    assert resolved["known"] is True
    assert resolved["symbol"] == EXCHANGE_SYMBOL
    assert resolved["source"] == "START_CONFIG_SYMBOL"


# =========================
# C: config XRPUSDTM -> XRPUSDTM
# =========================

def test_config_symbol_xrpusdtm_resolves_exchange_symbol():
    bot = _bot(_active_symbol=None, orderbook_symbol=None, config={"symbol": "XRPUSDTM"})

    resolved = bot.resolve_read_only_symbol()

    assert resolved["known"] is True
    assert resolved["symbol"] == EXCHANGE_SYMBOL
    assert resolved["source"] == "START_CONFIG_SYMBOL"


# =========================
# D: no authority -> known false
# =========================

def test_no_symbol_authority_returns_unavailable():
    bot = _bot(_active_symbol=None, orderbook_symbol=None, config={})

    resolved = bot.resolve_read_only_symbol()

    assert resolved["known"] is False
    assert resolved["symbol"] is None
    assert resolved["reason"] == SYMBOL_AUTHORITY_UNAVAILABLE


def test_blank_and_placeholder_config_values_are_absent():
    for value in (None, "", "   ", "NONE", "null", "unknown"):
        bot = _bot(_active_symbol=None, orderbook_symbol=None, config={"symbol": value})
        resolved = bot.resolve_read_only_symbol()
        assert resolved["known"] is False, value
        assert resolved["symbol"] is None, value


# =========================
# H: runtime beats config
# =========================

def test_runtime_symbol_wins_over_conflicting_config():
    bot = _bot(
        _running=True,
        _active_symbol="ETHUSDT",
        orderbook_symbol="ETHUSDTM",
        config={"symbol": "XRPUSDT"},
    )

    resolved = bot.resolve_read_only_symbol()

    assert resolved["known"] is True
    assert resolved["symbol"] == "ETHUSDTM"
    assert resolved["source"] == "ACTIVE_RUNTIME_SYMBOL"


# =========================
# E/F/G: absent symbol -> no exchange request
# =========================

def _guarded_client():
    client = KucoinTradeClient(
        api_key="key",
        api_secret="secret",
        passphrase="passphrase",
    )
    calls = {"gets": 0}

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls["gets"] += 1
        return _FakeResponse(
            {
                "code": "200000",
                "data": {"symbol": EXCHANGE_SYMBOL, "marginMode": "ISOLATED"},
            }
        )

    client.session.get = fake_get
    return client, calls


@pytest.mark.parametrize("value", [None, "", "   ", "NONE", "NULL", "UNKNOWN"])
def test_absent_symbol_never_triggers_exchange_request(value):
    client, calls = _guarded_client()

    authority = client.get_margin_mode(value)

    assert calls["gets"] == 0
    assert authority["available"] is False
    assert authority["marginMode"] is None
    assert authority["reason"] == MARGIN_MODE_AUTHORITY_UNAVAILABLE


def test_absent_snapshot_guard_set_matches_contract():
    assert ABSENT_SYMBOL_VALUES == {"", "NONE", "NULL", "UNKNOWN"}


# =========================
# I/J/K/L: margin-mode projection
# =========================

def _projection_client(authority=None, margin=None, raises=None):
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
    if authority is not None:
        client.margin_mode_authority.return_value = authority
    if margin is not None:
        if raises is not None:
            client.get_margin_mode.side_effect = raises
        else:
            client.get_margin_mode.return_value = margin
    return client


def _projection_bot(client, **kwargs):
    bot = _bot(_active_symbol=SYMBOL, config={"symbol": SYMBOL}, **kwargs)
    bot.account_read_client = client
    bot.account_read_client_exchange = "kucoin"
    return bot


def test_projection_configured_symbol_cross_is_mismatch(monkeypatch):
    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)
    client = _projection_client(authority={
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "CROSS",
        "compatible": False,
        "reason": MARGIN_MODE_MISMATCH,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    })
    bot = _projection_bot(client)

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["actualMarginMode"] == "CROSS"
    assert snapshot["marginModeKnown"] is True
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == MARGIN_MODE_MISMATCH


def test_projection_configured_symbol_isolated_is_compatible(monkeypatch):
    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)
    client = _projection_client(authority={
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "ISOLATED",
        "compatible": True,
        "reason": MARGIN_MODE_COMPATIBLE,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    })
    bot = _projection_bot(client)

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["marginModeKnown"] is True
    assert snapshot["marginModeCompatible"] is True
    assert snapshot["marginModeReason"] == MARGIN_MODE_COMPATIBLE


def test_projection_symbol_unavailable_never_queries_and_fails_closed(monkeypatch):
    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)
    client = _projection_client(authority={
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "CROSS",
        "compatible": False,
        "reason": MARGIN_MODE_MISMATCH,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    })
    bot = _bot(_active_symbol=None, orderbook_symbol=None, config={})
    bot.account_read_client = client
    bot.account_read_client_exchange = "kucoin"

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["actualMarginMode"] == "UNKNOWN"
    assert snapshot["marginModeKnown"] is False
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == MARGIN_MODE_AUTHORITY_UNAVAILABLE
    client.margin_mode_authority.assert_not_called()
    client.get_margin_mode.assert_not_called()


def test_projection_get_error_fails_closed(monkeypatch):
    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)
    client = _projection_client(margin={
        "symbol": EXCHANGE_SYMBOL,
        "marginMode": None,
        "available": False,
        "source": MARGIN_MODE_SOURCE,
        "reason": "MARGIN_MODE_AUTHORITY_REQUEST_FAILED",
        "updatedAt": None,
    })
    bot = _projection_bot(client)

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["actualMarginMode"] == "UNKNOWN"
    assert snapshot["marginModeKnown"] is False
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == MARGIN_MODE_AUTHORITY_UNAVAILABLE


def test_projection_resolved_symbol_is_reported(monkeypatch):
    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)
    client = _projection_client(authority={
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "CROSS",
        "compatible": False,
        "reason": MARGIN_MODE_MISMATCH,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    })
    bot = _projection_bot(client)

    snapshot = bot._refresh_real_account_snapshot("kucoin")

    assert snapshot["requiredMarginMode"] == REQUESTED_MARGIN_MODE


# =========================
# M: resolver is pure
# =========================

def test_resolver_does_not_mutate_state():
    bot = _bot(
        _active_symbol=SYMBOL,
        orderbook_symbol=EXCHANGE_SYMBOL,
        config={"symbol": SYMBOL, "mode": "live"},
        selection_mode="MANUAL",
    )
    before = (
        bot._active_symbol,
        bot.orderbook_symbol,
        dict(bot.config),
        bot.selection_mode,
    )

    for _ in range(5):
        bot.resolve_read_only_symbol()

    after = (
        bot._active_symbol,
        bot.orderbook_symbol,
        dict(bot.config),
        bot.selection_mode,
    )
    assert before == after


def test_manual_preparation_symbol_unavailable_does_not_query():
    manager = _bot(_active_symbol=None, orderbook_symbol=None, config={})
    client = Mock()
    client.margin_mode_authority.return_value = {
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "CROSS",
        "compatible": False,
        "reason": MARGIN_MODE_MISMATCH,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    }
    manager.account_read_client = client

    authority = manager._manual_preparation_margin_mode_authority(None)

    assert authority["known"] is False
    assert authority["reason"] == MARGIN_MODE_AUTHORITY_UNAVAILABLE
    client.margin_mode_authority.assert_not_called()
