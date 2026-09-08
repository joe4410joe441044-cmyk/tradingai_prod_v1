"""TRADINGAI-LIVE-AUTHORITY-AND-NORMAL-CLOSE-REPAIR-1: focused AA-2 contract tests.

Proves the LIVE order-entry authority model (operator-gated ARM/DISARM, fail
closed, no silent auto-arm, LIVE runtime distinct from real-order entry), the
normal LIVE close path (real reduceOnly exchange close, fail-closed on
partial/unknown/reject), PAPER close regression, and the
``/api/bot/set_mode`` operator-auth + CSRF repair.

All tests are isolated mocks / test doubles.  No real order is ever submitted,
no real position is created, and no LIVE runtime is started.
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("TEST_MODE", "1")

from backend import config as backend_config
from backend.api import bot_api
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    OperatorCsrfProtection,
)
from backend.auth.operator_auth import (
    OperatorAuthenticator,
    hash_operator_credential,
)
from backend.auth.operator_session import (
    COOKIE_NAME,
    OperatorSessionManager,
)
from backend.auth.api import create_operator_auth_router
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.bot_manager.bot_manager import BotManager
from backend.routers import mode as mode_router
from backend.runtime.governance_runtime import governance_state
from Bot.engine.execution_engine import ExecutionEngine


SESSION_SECRET = "b" * 32
TEST_CREDENTIAL = "live-authority-operator-credential-1"
TEST_CREDENTIAL_HASH = hash_operator_credential(TEST_CREDENTIAL)


# =========================
# ExecutionEngine helpers
# =========================

def _exchange(flatten_result=None):
    exchange = Mock()
    exchange.api_key = "k"
    exchange.api_secret = "s"
    exchange.passphrase = "p"
    exchange.place_order.return_value = {"success": True}
    if flatten_result is not None:
        exchange.flatten_current_position.return_value = flatten_result
    return exchange


def _ready_engine(exchange=None):
    engine = ExecutionEngine(
        exchange=exchange or _exchange(),
        portfolio=SimpleNamespace(initial_balance=1000, balance=1000),
    )
    engine.mode = "live"
    engine.symbol = "XRPUSDT"
    engine.status = "RUNNING"
    engine.price_ready = True
    engine.latest_price = 100
    engine.config["mode"] = "live"
    engine.config["dry_run"] = False
    engine.exchange_auth_ready = True
    engine.balance_check_ok = True
    engine.position_check_ok = True
    engine.balance_check_error = None
    engine.position_check_error = None
    engine.real_balance = 1000
    engine.real_equity = 1000
    engine.real_available_balance = 1000
    engine.real_position = None
    engine.real_position_state = "FLAT"
    engine.real_account_snapshot = {}
    engine.real_account_last_sync = time.time()
    engine.get_price = lambda: 100
    engine.update_drawdown_state = lambda *args: {"riskTradingDisabled": False}
    return engine


def _position(side="long"):
    return {
        "side": side,
        "qty": 10,
        "multiplier": 0.001,
        "entry_price": 100,
        "entry_time": time.time(),
        "order_id": "live-open-1",
        "trace_id": "trace-1",
        "runtimeSymbolContext": {
            "contextKey": "CTX-1",
            "runtimeInstanceId": "RID-1",
            "runtimeId": "RT-1",
            "exchangeSymbol": "XRPUSDTM",
        },
    }


def _patch_live_globals(**overrides):
    """Patch backend global LIVE config + governance_state to a safe LIVE set."""
    gov = dict(governance_state)
    exec_enabled = overrides.pop("execution_enabled", True)
    emergency = overrides.pop("emergency_stop", False)
    emergency_state = overrides.pop("emergency_state", "READY")

    def _apply():
        governance_state["execution_enabled"] = exec_enabled
        governance_state["emergency_stop"] = emergency
        governance_state["emergency_state"] = emergency_state
        governance_state.update(overrides)

    _apply()

    class GlobalPatch:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            governance_state.clear()
            governance_state.update(gov)

    return GlobalPatch()


# =========================
# BotManager helpers
# =========================

class FakeEngine:
    """Stand-in engine exposing the authority boundary used by BotManager ARM."""

    def __init__(self, block_reasons=None):
        self.config = {"mode": "live", "dry_run": False,
                       "liveOrderEntryAllowed": False}
        self.block_reasons = list(block_reasons or [])
        self.armed_calls = []

    def build_live_readiness(self):
        return {
            "realOrderAllowed": False,
            "blockReasons": list(self.block_reasons),
        }

    def set_live_order_entry_authority(self, armed):
        self.armed_calls.append(armed)
        if armed and self.block_reasons:
            return {
                "success": False,
                "armed": False,
                "reason": self.block_reasons[0],
                "blockReasons": list(self.block_reasons),
            }
        self.config["liveOrderEntryAllowed"] = bool(armed)
        return {
            "success": True,
            "armed": bool(armed),
            "liveOrderEntryAllowed": bool(armed),
            "realOrderAllowed": bool(armed),
            "executionEntryAllowed": bool(armed),
        }


def _arm_manager(engine=None, pending=None):
    manager = BotManager()
    manager.config = {"mode": "live", "dry_run": False}
    manager.engine = engine or FakeEngine()
    manager.get_authoritative_pending_order_state = lambda: (
        pending
        or {"known": True, "pending": False, "safe": True}
    )
    return manager


# =========================
# LIVE runtime / order-entry separation (A, B)
# =========================

def test_a_live_runtime_start_allowed_while_order_entry_disarmed():
    engine = _ready_engine()
    engine.config["liveRuntimeStartAllowed"] = True
    # Runtime may be allowed while real-order entry remains DISARMED.
    assert engine.config.get("liveRuntimeStartAllowed") is True
    assert engine.config.get("liveOrderEntryAllowed") is not True
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        readiness = engine.build_live_readiness()
    # realOrderAllowed stays False while entry is disarmed, even though the
    # runtime may operate.
    assert readiness["realOrderAllowed"] is False
    assert "LIVE_ORDER_ENTRY_DISARMED" in readiness["blockReasons"]


def test_b_live_start_does_not_auto_arm_order_entry():
    engine = _ready_engine()
    # Mirror START's live-branch config update: runtime allowed, order entry
    # left disarmed (never set True here).
    engine.config.update({
        "liveRuntimeStartAllowed": True,
        "liveOrderEntryAllowed": False,
        "realOrderAllowed": False,
        "executionEntryAllowed": False,
    })
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        readiness = engine.build_live_readiness()
        # Before any explicit arming, START alone must NOT produce a
        # real-order-allowed runtime.
        assert readiness["realOrderAllowed"] is False
        assert engine.config["liveOrderEntryAllowed"] is False
        # Only the explicit operator arming action lifts it.
        armed = engine.set_live_order_entry_authority(True)
        assert armed["success"] is True
        assert armed["armed"] is True
        assert engine.config["liveOrderEntryAllowed"] is True
        assert engine.build_live_readiness()["realOrderAllowed"] is True


def test_execution_engine_final_guard_blocks_disarmed_live_before_mm():
    engine = _ready_engine()
    engine.config.update({
        "realOrderAllowed": False,
        "executionEntryAllowed": False,
        "liveOrderEntryAllowed": False,
    })
    allowed, rejection = engine._evaluate_execution_entry_guard({
        "symbol": "XRPUSDTM", "side": "BUY", "qty": 1,
    })
    assert allowed is False
    assert rejection["reason"] == "LIVE_ORDER_ENTRY_DISARMED"
    assert rejection["providerCall"] is False
    assert rejection["exchangeCall"] is False
    # And even with the flags all True, governance (execution_enabled) denies.
    engine.config.update({
        "realOrderAllowed": True,
        "executionEntryAllowed": True,
        "liveOrderEntryAllowed": True,
    })
    engine.config["mode"] = "live"
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals(execution_enabled=False):
        assert engine._live_order_allowed() is False


# =========================
# Operator ARM contract (D, E, F, G, H, I, J, K)
# =========================

def _assert_arm_rejected(result, reason):
    assert result["success"] is False
    assert result["armed"] is False
    assert result["liveOrderEntryAllowed"] is False
    assert result["realOrderAllowed"] is False
    assert result["executionEntryAllowed"] is False
    assert result["reason"] == reason


def test_d_arm_succeeds_when_all_prerequisites_safe():
    manager = _arm_manager()
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = manager.set_live_order_entry_authority(True)
    assert result["success"] is True
    assert result["armed"] is True
    assert result["liveOrderEntryAllowed"] is True
    assert result["realOrderAllowed"] is True
    assert result["executionEntryAllowed"] is True
    assert manager.config["liveOrderEntryAllowed"] is True


def test_e_arm_fails_closed_when_emergency_active():
    manager = _arm_manager()
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals(emergency_stop=True):
        result = manager.set_live_order_entry_authority(True)
    _assert_arm_rejected(result, "EMERGENCY_STOP_ACTIVE")
    assert manager.config.get("liveOrderEntryAllowed") is not True


def test_f_arm_fails_closed_when_mode_not_live():
    manager = _arm_manager()
    manager.config["mode"] = "paper"
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = manager.set_live_order_entry_authority(True)
    _assert_arm_rejected(result, "SELECTED_MODE_NOT_LIVE")
    assert manager.config.get("liveOrderEntryAllowed") is not True


def test_g_arm_fails_closed_when_dry_run_true():
    manager = _arm_manager()
    manager.config["dry_run"] = True
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = manager.set_live_order_entry_authority(True)
    _assert_arm_rejected(result, "DRY_RUN_ACTIVE")
    assert manager.config.get("liveOrderEntryAllowed") is not True


@pytest.mark.parametrize("pending_kwargs", [
    {"known": False, "pending": None, "safe": False},
    {"known": True, "pending": True, "safe": False},
    {"known": True, "pending": False, "safe": False},
])
def test_h_arm_fails_closed_when_pending_order_authority_unsafe(pending_kwargs):
    manager = _arm_manager(
        pending={"reason": "PENDING_ORDER_REMAINING", **pending_kwargs}
    )
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = manager.set_live_order_entry_authority(True)
    _assert_arm_rejected(result, "PENDING_ORDER_REMAINING")
    assert manager.config.get("liveOrderEntryAllowed") is not True


def test_k_execution_entry_allowed_remains_false_when_engine_denies():
    # Engine-level position/real-account authority is unsafe => ARM fails and
    # executionEntryAllowed remains false.
    manager = _arm_manager(engine=FakeEngine(block_reasons=["BALANCE_CHECK_FAILED"]))
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = manager.set_live_order_entry_authority(True)
    assert result["success"] is False
    assert result["executionEntryAllowed"] is False
    assert result["reason"] == "BALANCE_CHECK_FAILED"
    assert manager.config.get("executionEntryAllowed") is not True


def test_i_disarm_prevents_new_entry_without_runtime_stop():
    manager = _arm_manager()
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        manager.set_live_order_entry_authority(True)
        assert manager.config["liveOrderEntryAllowed"] is True

    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = manager.set_live_order_entry_authority(False)
    assert result["success"] is True
    assert result["armed"] is False
    assert manager.config.get("liveOrderEntryAllowed") is not True
    assert manager.engine.config["liveOrderEntryAllowed"] is False
    # Runtime / monitoring is preserved (engine still present).
    assert manager.engine is not None


def test_j_no_unrelated_transition_silently_rearms():
    manager = _arm_manager()
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        manager.set_live_order_entry_authority(True)
        manager.set_live_order_entry_authority(False)
        assert manager.config.get("liveOrderEntryAllowed") is not True
    # Once disarmed, enabling auto-trade (a separate lifecycle transition)
    # must NOT rearm real order entry; it is refused while disarmed.
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        manager._running = True
        manager.lifecycle_state = "RUNNING"
        manager.loop_state = "RUNNING"
        res = manager.set_execution_enabled(True)
    assert res["success"] is False
    assert res["reason"] == "LIVE_ORDER_ENTRY_DISARMED"
    assert manager.config.get("liveOrderEntryAllowed") is not True


# =========================
# Normal LIVE close (L, M, N, O, P, Q)
# =========================

CONFIRMED = {
    "success": True, "accepted": True, "confirmed": True, "closed": True,
    "skipped": False, "symbol": "XRPUSDTM", "order_id": "close-1",
    "raw_order": {"code": "200000"}, "final_position": {"found": False},
}
REJECTED = {
    "success": False, "accepted": False, "confirmed": False, "closed": False,
    "skipped": False, "symbol": "XRPUSDTM", "error_code": "API_ERROR",
}
TIMEOUT = {
    "success": False, "accepted": True, "confirmed": False, "closed": False,
    "skipped": False, "symbol": "XRPUSDTM", "error_code": "TIMEOUT",
}
PARTIAL = {
    "success": False, "accepted": True, "confirmed": False, "closed": False,
    "skipped": False, "symbol": "XRPUSDTM", "error_code": "POSITION_REMAINS",
}


def _close_engine(flatten_result):
    engine = _ready_engine(exchange=_exchange(flatten_result))
    engine.actual_position = _position("long")
    return engine


def test_l_normal_live_exit_calls_exchange_reduceonly_close_primitive():
    engine = _close_engine(CONFIRMED)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        engine.close_position(101.0, "SL")
    # The real exchange reduceOnly flatten primitive is reused.
    engine.exchange.flatten_current_position.assert_called_once_with("XRPUSDT")


def test_m_paper_close_remains_simulation_only():
    exchange = _exchange(CONFIRMED)
    portfolio = SimpleNamespace(
        initial_balance=1000,
        balance=1000,
        get_positions=lambda: {},
        close_position=lambda symbol, price: 0,
    )
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=portfolio,
    )
    engine.mode = "paper"
    engine.symbol = "XRPUSDT"
    engine.config["mode"] = "paper"
    engine.config["dry_run"] = True
    engine.actual_position = _position("long")
    engine.get_price = lambda: 100
    result = engine.close_position(101.0, "TP")
    assert engine.mode == "paper"
    # No real exchange close primitive call, no live close state.
    exchange.flatten_current_position.assert_not_called()
    assert engine.actual_position is None
    assert engine.live_close_state is None
    assert result is None


def test_n_live_close_rejection_does_not_mark_flat():
    engine = _close_engine(REJECTED)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = engine.close_position(101.0, "SL")
    assert result["confirmed"] is False
    assert result["status"] == "REJECTED"
    # Position is preserved, NOT marked flat.
    assert engine.actual_position is not None
    assert engine.actual_position["order_id"] == "live-open-1"


def test_o_live_close_unknown_or_timeout_does_not_mark_flat():
    engine = _close_engine(TIMEOUT)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = engine.close_position(101.0, "SL")
    assert result["confirmed"] is False
    assert result["status"] == "UNKNOWN"
    assert engine.actual_position is not None
    assert engine.live_close_in_flight is True


def test_o2_repeated_blind_close_guard_prevents_resend():
    engine = _close_engine(TIMEOUT)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        engine.close_position(101.0, "SL")
    # A second tick must NOT resend a blind close while unconfirmed.
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        engine.close_position(101.0, "SL")
    assert engine.exchange.flatten_current_position.call_count == 1
    assert engine.actual_position is not None


def test_p_confirmed_real_close_allows_flat_transition():
    engine = _close_engine(CONFIRMED)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        result = engine.close_position(101.0, "SL")
    assert result["confirmed"] is True
    assert result["closed"] is True
    assert engine.actual_position is None
    assert engine.live_close_in_flight is False
    assert engine.live_close_state["status"] == "CONFIRMED"


def test_q_canonical_identity_preserved_through_close():
    engine = _close_engine(CONFIRMED)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ), _patch_live_globals():
        engine.close_position(101.0, "MICROSTRUCTURE_EXIT")
    record = engine.trade_history[-1]
    assert record["contextKey"] == "CTX-1"
    assert record["runtimeInstanceId"] == "RID-1"
    assert record["exchangeSymbol"] == "XRPUSDTM"
    # The exchange close was addressed to the canonical runtime symbol.
    engine.exchange.flatten_current_position.assert_called_once_with("XRPUSDT")


# =========================
# /api/bot/set_mode security (R, S)
# =========================

def _build_set_mode_app(session_ttl=3600):
    config = OperatorAuthConfig(
        credential_hash=TEST_CREDENTIAL_HASH,
        session_secret=SESSION_SECRET,
        session_ttl_seconds=session_ttl,
        secure_cookie=False,
        cookie_path="/",
        cookie_samesite="lax",
    )
    manager = OperatorSessionManager(SESSION_SECRET, session_ttl)
    authenticator = OperatorAuthenticator(TEST_CREDENTIAL_HASH)

    app = FastAPI()
    app.add_middleware(
        OperatorSessionMiddleware,
        session_manager=manager,
        config=config,
    )
    app.add_middleware(
        OperatorCsrfProtection,
        csrf_required_paths=frozenset({"/api/bot/set_mode"}),
    )
    app.include_router(create_operator_auth_router(authenticator, manager, config))
    app.include_router(mode_router.router, prefix="/api/bot")
    return app


def _extract_cookie(response, name):
    for header in response.headers.get_list("set-cookie"):
        for part in header.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                if key.strip() == name:
                    return value.strip()
    return None


def _login(client):
    resp = client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
    assert resp.status_code == 200, resp.text
    session = _extract_cookie(resp, COOKIE_NAME)
    csrf = _extract_cookie(resp, CSRF_TOKEN_COOKIE)
    assert session and csrf
    return session, csrf


def test_r_set_mode_rejects_unauthenticated_mutation():
    client = TestClient(_build_set_mode_app(), raise_server_exceptions=False)
    resp = client.post("/api/bot/set_mode", json={"mode": "live"})
    # No session and no CSRF token: rejected (401 session or 403 CSRF).
    assert resp.status_code in (401, 403)


def test_r_set_mode_rejects_authenticated_missing_csrf():
    client = TestClient(_build_set_mode_app(), raise_server_exceptions=False)
    session, _csrf = _login(client)
    resp = client.post(
        "/api/bot/set_mode",
        json={"mode": "paper"},
        cookies={COOKIE_NAME: session},
    )
    assert resp.status_code == 403


def test_s_set_mode_valid_operator_retains_behavior():
    client = TestClient(_build_set_mode_app(), raise_server_exceptions=False)
    session, csrf = _login(client)
    with patch.object(backend_config, "ALLOW_LIVE", False), patch.object(
        backend_config, "TRADE_MODE", "paper"
    ):
        resp = client.post(
            "/api/bot/set_mode",
            json={"mode": "live"},
            cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
            headers={CSRF_TOKEN_HEADER: csrf},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["mode"] == "live"
        assert backend_config.ALLOW_LIVE is True
        assert backend_config.TRADE_MODE == "live"


def test_s_set_mode_invalid_mode_rejected():
    client = TestClient(_build_set_mode_app(), raise_server_exceptions=False)
    session, csrf = _login(client)
    resp = client.post(
        "/api/bot/set_mode",
        json={"mode": "simulation"},
        cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
        headers={CSRF_TOKEN_HEADER: csrf},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["reason"] == "INVALID_MODE"
