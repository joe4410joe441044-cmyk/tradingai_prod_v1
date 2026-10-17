"""D-LIVE-4F-1: durable configured-symbol authority.

Pins the durable backend configured-symbol contract that the D-LIVE-4F STOPPED
projection needs:

* ``configuredSymbol`` is the ONE canonical backend authority for the
  operator-committed MANUAL trading destination;
* it survives a clean BotManager / process restart and is available while
  STOPPED with no runtime, no engine, and no previous START in the process;
* saving it never starts / arms / creates an engine / places an order / changes
  execution or margin authority;
* the read-only resolver prefers it while STOPPED but never lets it override a
  live runtime symbol, and never lets stale in-memory START config override it;
* the MANUAL START boundary atomically (re)establishes it; AUTO selection never
  writes the MANUAL destination.

All tests are isolated and perform no LIVE START / ARM / order / exchange
mutation.
"""

import json
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import bot_api
from backend.auth.dependencies import require_operator_session
from backend.bot_manager.bot_manager import (
    BotManager,
    CONFIGURED_SYMBOL_SCHEMA_VERSION,
    SYMBOL_AUTHORITY_RESOLVED,
    SYMBOL_AUTHORITY_UNAVAILABLE,
)
from backend.execution.kucoin_trade import (
    KucoinTradeClient,
    MARGIN_MODE_AUTHORITY_UNAVAILABLE,
    MARGIN_MODE_COMPATIBLE,
    MARGIN_MODE_MISMATCH,
    MARGIN_MODE_SOURCE,
    REQUESTED_MARGIN_MODE,
)

SYMBOL = "XRPUSDT"
EXCHANGE_SYMBOL = "XRPUSDTM"


def _manager(tmp_path, name="configured_symbol_authority.json", **attrs):
    manager = BotManager(configured_symbol_path=str(tmp_path / name))
    for key, value in attrs.items():
        setattr(manager, key, value)
    return manager


def _projection_client(margin=None, authority=None):
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
        client.get_margin_mode.return_value = margin
    return client


# =========================
# 1. Persistence / normalization
# =========================

def test_default_configured_symbol_is_unavailable(tmp_path):
    manager = _manager(tmp_path)

    assert manager.get_configured_symbol() is None
    assert manager.configured_symbol_revision == 0
    resolved = manager.resolve_read_only_symbol()
    assert resolved["known"] is False
    assert resolved["reason"] == SYMBOL_AUTHORITY_UNAVAILABLE


def test_set_configured_symbol_normalizes_xrpusdt(tmp_path):
    manager = _manager(tmp_path)

    result = manager.set_configured_symbol(SYMBOL)

    assert result["success"] is True
    assert result["configuredSymbol"] == EXCHANGE_SYMBOL
    assert manager.get_configured_symbol() == EXCHANGE_SYMBOL
    assert manager.configured_symbol_revision == 1


def test_set_configured_symbol_normalizes_xrpusdtm(tmp_path):
    manager = _manager(tmp_path)

    result = manager.set_configured_symbol(EXCHANGE_SYMBOL)

    assert result["success"] is True
    assert result["configuredSymbol"] == EXCHANGE_SYMBOL


def test_same_configured_symbol_is_noop_without_revision_or_persist(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(EXCHANGE_SYMBOL)
    revision = manager.configured_symbol_revision
    updated_at = manager.configured_symbol_updated_at

    with patch.object(manager, "_persist_configured_symbol_authority") as persist:
        result = manager.set_configured_symbol(EXCHANGE_SYMBOL)

    assert result == {
        "success": True,
        "changed": False,
        "configuredSymbol": EXCHANGE_SYMBOL,
        "configuredSymbolRevision": revision,
        "configuredSymbolUpdatedAt": updated_at,
    }
    assert manager.configured_symbol_revision == revision
    assert persist.call_count == 0


def test_normalization_equivalent_configured_symbol_is_noop(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(EXCHANGE_SYMBOL)
    revision = manager.configured_symbol_revision

    with patch.object(manager, "_persist_configured_symbol_authority") as persist:
        result = manager.set_configured_symbol(SYMBOL)

    assert result["success"] is True
    assert result["changed"] is False
    assert result["configuredSymbol"] == EXCHANGE_SYMBOL
    assert result["configuredSymbolRevision"] == revision
    assert manager.configured_symbol_revision == revision
    assert persist.call_count == 0


def test_different_configured_symbol_increments_and_persists_once(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(EXCHANGE_SYMBOL)
    revision = manager.configured_symbol_revision

    with patch.object(
        manager,
        "_persist_configured_symbol_authority",
        wraps=manager._persist_configured_symbol_authority,
    ) as persist:
        result = manager.set_configured_symbol("ETHUSDT")

    assert result["success"] is True
    assert result["changed"] is True
    assert result["configuredSymbol"] == "ETHUSDTM"
    assert result["configuredSymbolRevision"] == revision + 1
    assert manager.configured_symbol_revision == revision + 1
    assert persist.call_count == 1


def test_invalid_configured_symbol_fails_closed_without_persist(tmp_path):
    manager = _manager(tmp_path)

    with patch.object(manager, "_persist_configured_symbol_authority") as persist:
        result = manager.set_configured_symbol("UNKNOWN")

    assert result["success"] is False
    assert result["reason"] == "INVALID_CONFIGURED_SYMBOL"
    assert manager.get_configured_symbol() is None
    assert manager.configured_symbol_revision == 0
    assert persist.call_count == 0


def test_same_symbol_after_restart_preserves_durable_authority_bytes(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"
    first = BotManager(configured_symbol_path=str(path))
    first.set_configured_symbol(EXCHANGE_SYMBOL)
    before = path.read_bytes()

    restarted = BotManager(configured_symbol_path=str(path))
    revision = restarted.configured_symbol_revision
    with patch.object(restarted, "_persist_configured_symbol_authority") as persist:
        result = restarted.set_configured_symbol(SYMBOL)

    assert result["success"] is True
    assert result["changed"] is False
    assert restarted.configured_symbol_revision == revision
    assert path.read_bytes() == before
    assert persist.call_count == 0


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "NONE", "NULL", "UNKNOWN", "NOT AVAILABLE", "not available"],
)
def test_set_configured_symbol_rejects_absent_and_placeholders(tmp_path, value):
    manager = _manager(tmp_path)

    result = manager.set_configured_symbol(value)

    assert result["success"] is False
    assert result["reason"] == "INVALID_CONFIGURED_SYMBOL"
    assert manager.get_configured_symbol() is None
    assert manager.configured_symbol_revision == 0


def test_stale_revision_is_rejected(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(SYMBOL)

    stale = manager.set_configured_symbol("ETHUSDT", expected_revision=0)
    assert stale["success"] is False
    assert stale["reason"] == "STALE_CONFIGURED_SYMBOL_REVISION"
    assert manager.get_configured_symbol() == EXCHANGE_SYMBOL


# =========================
# 2. Clean-restart durability
# =========================

def test_configured_symbol_is_durable_across_manager_restart(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"

    first = BotManager(configured_symbol_path=str(path))
    first.set_configured_symbol(SYMBOL)

    second = BotManager(configured_symbol_path=str(path))
    assert second.get_configured_symbol() == EXCHANGE_SYMBOL
    assert second.configured_symbol_revision == 1


def test_clean_restart_stopped_resolver_uses_configured_symbol(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"

    first = BotManager(configured_symbol_path=str(path))
    first.set_configured_symbol(SYMBOL)

    # A brand-new process-equivalent object: no START, no engine, no runtime.
    second = BotManager(configured_symbol_path=str(path))
    assert second._running is False
    assert second._active_symbol is None
    assert second.orderbook_symbol is None
    assert second.config == {}

    resolved = second.resolve_read_only_symbol()
    assert resolved["known"] is True
    assert resolved["symbol"] == EXCHANGE_SYMBOL
    assert resolved["canonicalSymbol"] == EXCHANGE_SYMBOL
    assert resolved["source"] == "CONFIGURED_SYMBOL"
    assert resolved["reason"] == SYMBOL_AUTHORITY_RESOLVED


def test_clean_restart_manual_preparation_uses_normalized_symbol(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"

    first = BotManager(configured_symbol_path=str(path))
    first.set_configured_symbol(SYMBOL)

    second = BotManager(configured_symbol_path=str(path))
    client = Mock()
    client.margin_mode_authority.return_value = {
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "ISOLATED",
        "compatible": True,
        "reason": MARGIN_MODE_COMPATIBLE,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    }
    second.account_read_client = client

    authority = second._manual_preparation_margin_mode_authority(None)

    assert authority["known"] is True
    assert authority["compatible"] is True
    client.margin_mode_authority.assert_called_once_with(EXCHANGE_SYMBOL)


# =========================
# 3. STOPPED margin projection (section 17 acceptance)
# =========================

def test_stopped_margin_projection_cross_is_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(KucoinTradeClient, "credentials_present", lambda *a, **k: True)
    path = tmp_path / "configured_symbol_authority.json"

    writer = BotManager(configured_symbol_path=str(path))
    writer.set_configured_symbol(SYMBOL)

    manager = BotManager(configured_symbol_path=str(path))
    client = _projection_client(authority={
        "known": True,
        "requiredMode": REQUESTED_MARGIN_MODE,
        "actualMode": "CROSS",
        "compatible": False,
        "reason": MARGIN_MODE_MISMATCH,
        "source": MARGIN_MODE_SOURCE,
        "updatedAt": 1.0,
    })
    manager.account_read_client = client
    manager.account_read_client_exchange = "kucoin"

    snapshot = manager._refresh_real_account_snapshot("kucoin")

    client.margin_mode_authority.assert_called_once_with(EXCHANGE_SYMBOL)
    assert snapshot["requiredMarginMode"] == REQUESTED_MARGIN_MODE
    assert snapshot["actualMarginMode"] == "CROSS"
    assert snapshot["marginModeKnown"] is True
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == MARGIN_MODE_MISMATCH


# =========================
# 4. Absent / corrupt state
# =========================

def test_missing_state_fails_closed_without_exchange_request(tmp_path):
    manager = _manager(tmp_path)
    client, calls = _guarded_client()
    manager.account_read_client = client

    snapshot = manager._refresh_real_account_snapshot("kucoin")

    assert snapshot["marginModeKnown"] is False
    assert snapshot["marginModeCompatible"] is False
    assert snapshot["marginModeReason"] == MARGIN_MODE_AUTHORITY_UNAVAILABLE
    assert calls["gets"] == 0


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"
    path.write_text("{not valid json", encoding="utf-8")

    manager = BotManager(configured_symbol_path=str(path))

    assert manager.get_configured_symbol() is None
    assert manager.configured_symbol_revision == 0


def test_invalid_persisted_symbol_fails_closed(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"
    path.write_text(
        json.dumps({"schemaVersion": CONFIGURED_SYMBOL_SCHEMA_VERSION,
                    "symbol": "NONE", "revision": 3, "updatedAt": 1.0}),
        encoding="utf-8",
    )

    manager = BotManager(configured_symbol_path=str(path))

    assert manager.get_configured_symbol() is None
    assert manager.configured_symbol_revision == 0


def test_negative_revision_fails_closed(tmp_path):
    path = tmp_path / "configured_symbol_authority.json"
    path.write_text(
        json.dumps({"symbol": "XRPUSDTM", "revision": -1}),
        encoding="utf-8",
    )

    manager = BotManager(configured_symbol_path=str(path))

    assert manager.get_configured_symbol() is None


# =========================
# 5. Conflict / precedence
# =========================

def test_configured_and_runtime_same_symbol_compatible(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(SYMBOL)
    manager._running = True
    manager._active_symbol = EXCHANGE_SYMBOL
    manager.orderbook_symbol = EXCHANGE_SYMBOL
    manager.config = {"symbol": SYMBOL}

    resolved = manager.resolve_read_only_symbol()

    assert resolved["known"] is True
    assert resolved["symbol"] == EXCHANGE_SYMBOL


def test_runtime_active_not_overwritten_while_running(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(SYMBOL)
    manager._running = True
    manager._active_symbol = "ETHUSDT"
    manager.orderbook_symbol = "ETHUSDTM"
    manager.config = {"symbol": SYMBOL}

    resolved = manager.resolve_read_only_symbol()

    assert resolved["symbol"] == "ETHUSDTM"
    assert resolved["source"] == "ACTIVE_RUNTIME_SYMBOL"


def test_stale_in_memory_start_config_does_not_override_configured(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(SYMBOL)
    manager._running = False
    manager._active_symbol = None
    manager.orderbook_symbol = None
    # Stale in-memory START config from a previous run.
    manager.config = {"symbol": "ETHUSDT"}

    resolved = manager.resolve_read_only_symbol()

    assert resolved["known"] is True
    assert resolved["symbol"] == EXCHANGE_SYMBOL
    assert resolved["source"] == "CONFIGURED_SYMBOL"


def test_resolver_is_pure_with_configured_symbol(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(SYMBOL)
    manager.config = {"symbol": SYMBOL, "mode": "paper"}
    before = (
        manager._active_symbol,
        manager.orderbook_symbol,
        dict(manager.config),
        manager.selection_mode,
        manager.get_configured_symbol(),
    )

    for _ in range(5):
        manager.resolve_read_only_symbol()

    after = (
        manager._active_symbol,
        manager.orderbook_symbol,
        dict(manager.config),
        manager.selection_mode,
        manager.get_configured_symbol(),
    )
    assert before == after


# =========================
# 6. MANUAL / AUTO boundary
# =========================

def test_manual_start_establishes_configured_symbol(tmp_path):
    manager = _manager(tmp_path)

    result = manager._establish_configured_symbol_on_start({
        "symbol": SYMBOL,
        "selection_mode": "MANUAL",
    })

    assert result["success"] is True
    assert manager.get_configured_symbol() == EXCHANGE_SYMBOL


def test_manual_start_same_symbol_does_not_mutate_authority(tmp_path):
    manager = _manager(tmp_path)
    manager.set_configured_symbol(EXCHANGE_SYMBOL)
    revision = manager.configured_symbol_revision
    engine = object()
    manager.engine = engine

    with patch.object(manager, "_persist_configured_symbol_authority") as persist:
        result = manager._establish_configured_symbol_on_start({
            "symbol": SYMBOL,
            "selection_mode": "MANUAL",
        })

    assert result["success"] is True
    assert result["changed"] is False
    assert manager.get_configured_symbol() == EXCHANGE_SYMBOL
    assert manager.configured_symbol_revision == revision
    assert manager.engine is engine
    assert persist.call_count == 0


def test_auto_start_never_writes_manual_destination(tmp_path):
    manager = _manager(tmp_path)

    result = manager._establish_configured_symbol_on_start({
        "symbol": SYMBOL,
        "selection_mode": "AUTO",
    })

    assert result["success"] is False
    assert result["reason"] == "CONFIGURED_SYMBOL_NOT_APPLICABLE"
    assert manager.get_configured_symbol() is None


def test_auto_start_does_not_change_selection_mode(tmp_path):
    manager = _manager(tmp_path)
    manager.selection_mode = "AUTO"
    manager.auto_market_selection_observation = {"topCandidate": "ETHUSDT"}

    manager._establish_configured_symbol_on_start({
        "symbol": SYMBOL,
        "selection_mode": "AUTO",
    })

    assert manager.selection_mode == "AUTO"
    assert manager.auto_market_selection_observation == {
        "topCandidate": "ETHUSDT"
    }
    assert manager.get_active_symbol_contract()["selectionMode"] == "AUTO"


# =========================
# 7. Save safety / no runtime side effects
# =========================

def test_save_configured_symbol_while_stopped_has_no_runtime_side_effect(tmp_path):
    manager = _manager(tmp_path)
    manager.engine = None
    manager._running = False
    manager.lifecycle_state = "STOPPED"
    manager.config = {"mode": "paper", "dry_run": True}

    before_status = manager.get_status()

    result = manager.set_configured_symbol(SYMBOL)
    assert result["success"] is True

    assert manager.engine is None
    assert manager._running is False
    assert manager.lifecycle_state == "STOPPED"
    assert manager.config.get("realOrderAllowed") is not True
    assert manager.config.get("liveOrderEntryAllowed") is not True
    assert manager.config.get("executionEntryAllowed") is not True

    status = manager.get_status()
    assert status["status"] == "STOPPED"
    assert status["runtimeMode"] == "NONE"
    assert status["executionMode"] == "SIMULATION"
    assert status["realOrderAllowed"] is False
    assert status["configuredSymbol"] == EXCHANGE_SYMBOL
    assert status["activeSymbol"] is None
    assert status["orderbookSymbol"] is None
    assert status["configuredSymbolRevision"] == 1
    # Only the configured-symbol fields changed.
    assert before_status["configuredSymbol"] is None


# =========================
# 8. Authenticated SAVE SETTINGS endpoint reuse
# =========================

def _api_client(manager):
    app = FastAPI()
    app.include_router(bot_api.router, prefix="/api/bot")
    app.dependency_overrides[require_operator_session] = lambda: "operator"
    return TestClient(app)


def test_saved_mode_endpoint_commits_symbol(tmp_path):
    manager = _manager(tmp_path)
    manager.engine = None
    manager._running = False

    with patch.object(bot_api, "get_bot_manager", return_value=manager):
        client = _api_client(manager)
        response = client.post(
            "/api/bot/saved-mode",
            json={"mode": "paper", "symbol": SYMBOL},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["configuredSymbol"] == EXCHANGE_SYMBOL
    assert manager.get_configured_symbol() == EXCHANGE_SYMBOL
    assert manager.engine is None
    assert manager._running is False


def test_saved_mode_endpoint_rejects_absent_symbol(tmp_path):
    manager = _manager(tmp_path)

    with patch.object(bot_api, "get_bot_manager", return_value=manager):
        client = _api_client(manager)
        response = client.post(
            "/api/bot/saved-mode",
            json={"mode": "paper", "symbol": "NONE"},
        )

    assert response.status_code == 422
    assert manager.get_configured_symbol() is None


def test_saved_mode_endpoint_still_supports_mode_only(tmp_path):
    manager = _manager(tmp_path)

    with patch.object(bot_api, "get_bot_manager", return_value=manager):
        client = _api_client(manager)
        response = client.post(
            "/api/bot/saved-mode",
            json={"mode": "live"},
        )

    assert response.status_code == 200
    assert response.json()["savedMode"] == "LIVE"
    assert manager.get_configured_symbol() is None


# =========================
# 9. NONE query guard (durable-path)
# =========================

class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


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
            {"code": "200000", "data": {"symbol": EXCHANGE_SYMBOL,
                                        "marginMode": "ISOLATED"}}
        )

    client.session.get = fake_get
    return client, calls


def test_configured_placeholder_never_reaches_exchange(tmp_path):
    manager = _manager(tmp_path)
    # A placeholder can never be committed; the in-memory value stays None.
    manager.set_configured_symbol("NOT AVAILABLE")

    resolved = manager.resolve_read_only_symbol()
    assert resolved["known"] is False

    client, calls = _guarded_client()
    for value in (None, "", "NONE", "NOT AVAILABLE"):
        client.get_margin_mode(value)
    assert calls["gets"] == 0
