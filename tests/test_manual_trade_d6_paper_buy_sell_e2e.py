"""TRADINGAI-MANUAL-TRADING-D6: authenticated HTTP PAPER BUY/SELL E2E.

Completes Work D by driving the exact required manual cycle through the real
authenticated operator HTTP boundary (login + session + CSRF), the real
BotManager, the real PAPER ExecutionEngine/PortfolioManager and the existing
Money-Management admission and Governance lifecycle:

    FLAT --BUY-->  ENTRY_LONG  --> LONG  --SELL--> CLOSE_LONG  --> FLAT
    FLAT --SELL--> ENTRY_SHORT --> SHORT --BUY-->  CLOSE_SHORT --> FLAT

There is no reversal and no REAL order. ``exchange=None`` is the existing
PAPER simulation boundary, so the engine can never reach an exchange client.
These tests never start a runtime, never place a LIVE order and never mutate
production state.
"""

import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("TEST_MODE", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Bot.engine.execution_engine import ExecutionEngine
from backend.api import bot_api
from backend.auth.api import create_operator_auth_router
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
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.bot_manager.bot_manager import (
    BotManager,
    CONTROL_AUTHORITY_BOT,
    CONTROL_AUTHORITY_MANUAL,
    MANUAL_OPERATION_CLOSE_LONG,
    MANUAL_OPERATION_CLOSE_SHORT,
    MANUAL_OPERATION_ENTRY_LONG,
    MANUAL_OPERATION_ENTRY_SHORT,
)
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionOperation,
)
from backend.money_management.loss_execution_integration import (
    LossExecutionAdmissionReason,
    LossExecutionAdmissionResult,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)


SYMBOL = "XRPUSDT"
EXCHANGE_SYMBOL = "XRPUSDTM"
RUNTIME_ID = "manual-d6-runtime-1"

PAPER_CAPITAL = 1000.0
POSITION_SIZE_CAP = 100.0
LEVERAGE = 5

SESSION_SECRET = "d" * 32
TEST_CREDENTIAL = "d6-operator-credential-6"
TEST_CREDENTIAL_HASH = hash_operator_credential(TEST_CREDENTIAL)

CSRF_PATHS = frozenset({
    "/api/bot/control",
    "/api/bot/manual-trade",
})


class PriceManager:
    def __init__(self, price):
        self.price = price

    def get_current_price(self):
        return self.price


class AdmissionRecorder:
    """Records the exact MM-requested quantity, then allows entry."""

    def __init__(self):
        self.intents = []

    def __call__(self, intent):
        self.intents.append(intent)
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


@pytest.fixture(autouse=True)
def _reset_governance():
    previous = dict(governance_state)
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    yield
    governance_state.clear()
    governance_state.update(previous)


def _build_manager(price=100.0):
    """Production-like PAPER runtime that starts under BOT control."""

    manager = BotManager()
    price_manager = PriceManager(price)
    portfolio = PortfolioManager(PAPER_CAPITAL)
    engine = ExecutionEngine(
        exchange=None,
        portfolio=portfolio,
        price_manager=price_manager,
    )
    engine.symbol = SYMBOL
    engine.set_config({
        "mode": "paper",
        "dry_run": True,
        "position_size": POSITION_SIZE_CAP,
        "leverage": LEVERAGE,
        "sl_percent": 1,
        "tp_percent": 2,
    })
    engine.status = "RUNNING"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = price

    recorder = AdmissionRecorder()
    from sizing_support import install_sizing
    install_sizing(engine)
    engine.set_execution_entry_guard(recorder)
    engine.set_execution_authority_guard(
        manager._dispatch_execution_authority_guard
    )

    manager.engine = engine
    manager.config = {"mode": "paper", "dry_run": True}
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "RUNNING"
    manager._running = True
    manager.active_runtime_id = RUNTIME_ID
    manager._active_symbol = SYMBOL
    manager.selection_mode = "MANUAL"
    manager.exchange_name = "kucoin"
    manager.market_type = "FUTURES"
    manager.orderbook_symbol = EXCHANGE_SYMBOL
    manager.state.position_state = "FLAT"
    manager.pending_order = False
    manager.get_authoritative_pending_order_state = lambda **kw: {
        "known": True,
        "pending": False,
        "safe": True,
        "pending_order": False,
        "reason": "NO_PENDING_ORDER",
    }

    governance_state["emergency_state"] = EMERGENCY_READY
    governance_state["emergency_stop"] = False

    # The runtime begins under BOT authority. The switch to MANUAL is driven
    # through the authenticated HTTP control route, never by direct mutation.
    manager.control_authority = CONTROL_AUTHORITY_BOT
    manager._mirror_control_authority()

    return manager, engine, portfolio, price_manager, recorder


def _build_app(manager):
    config = OperatorAuthConfig(
        credential_hash=TEST_CREDENTIAL_HASH,
        session_secret=SESSION_SECRET,
        session_ttl_seconds=3600,
        secure_cookie=False,
        cookie_path="/",
        cookie_samesite="lax",
    )
    session_manager = OperatorSessionManager(SESSION_SECRET, 3600)
    authenticator = OperatorAuthenticator(TEST_CREDENTIAL_HASH)

    app = FastAPI()
    app.add_middleware(
        OperatorSessionMiddleware,
        session_manager=session_manager,
        config=config,
    )
    app.add_middleware(
        OperatorCsrfProtection,
        csrf_required_paths=CSRF_PATHS,
    )
    app.include_router(
        create_operator_auth_router(authenticator, session_manager, config)
    )
    app.include_router(bot_api.router, prefix="/api/bot")
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


class Harness:
    def __init__(self, price=100.0):
        self.manager, self.engine, self.portfolio, self.price, self.recorder = (
            _build_manager(price=price)
        )
        self.app = _build_app(self.manager)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._patch = patch(
            "backend.api.bot_api.get_bot_manager",
            return_value=self.manager,
        )
        self._patch.start()
        resp = self.client.post(
            "/api/auth/login", json={"credential": TEST_CREDENTIAL}
        )
        assert resp.status_code == 200, resp.text
        self.session = _extract_cookie(resp, COOKIE_NAME)
        self.csrf = _extract_cookie(resp, CSRF_TOKEN_COOKIE)
        assert self.session and self.csrf

    def close(self):
        self._patch.stop()

    def _cookies(self):
        return {
            COOKIE_NAME: self.session,
            CSRF_TOKEN_COOKIE: self.csrf,
        }

    def switch_manual(self):
        resp = self.client.post(
            "/api/bot/control",
            json={"authority": "MANUAL"},
            cookies=self._cookies(),
            headers={CSRF_TOKEN_HEADER: self.csrf},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def trade(self, action, request_id):
        resp = self.client.post(
            "/api/bot/manual-trade",
            json={"action": action, "requestId": request_id,
                  "expectedMode": "paper", "expectedSymbol": SYMBOL,
                  "expectedControlRevision": self.manager.control_revision},
            cookies=self._cookies(),
            headers={CSRF_TOKEN_HEADER: self.csrf},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def preparation(self):
        resp = self.client.get("/api/bot/manual-trade/preparation")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def position_state(self):
        return self.manager._execution_control_position_state()


@pytest.fixture
def harness():
    h = Harness()
    yield h
    h.close()


def _assert_no_real_order(harness):
    # The PAPER simulation boundary: no exchange client can ever be reached.
    assert harness.engine.exchange is None
    assert str(harness.engine.mode).strip().lower() == "paper"
    assert harness.engine.config.get("dry_run") is True
    # Every fill is a simulated PAPER fill.
    for fill in harness.engine.paper_fills:
        assert fill.get("fillType") in ("ENTRY", "CLOSE")
    for order in harness.engine.paper_orders:
        assert order.get("qty", 0) > 0


# =========================
# LIGHTWEIGHT REVALIDATION
# =========================

def test_d6_revalidation_paper_flat_bot_then_manual_control(harness):
    prep = harness.preparation()
    assert prep["mode"] == "paper"
    assert prep["symbol"] == SYMBOL
    assert prep["positionState"] == "FLAT"
    assert prep["pending"] is False
    assert prep["controlAuthority"] == CONTROL_AUTHORITY_BOT
    assert prep["valid"] is True
    assert prep["candidate"]["quantityUnit"] == "coin"

    switched = harness.switch_manual()
    assert switched["success"] is True
    assert switched["changed"] is True
    assert switched["controlAuthority"] == CONTROL_AUTHORITY_MANUAL

    after = harness.preparation()
    assert after["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert after["positionState"] == "FLAT"
    assert after["pending"] is False


def test_d6_control_switch_requires_authentication_and_csrf(harness):
    before = dict(governance_state)
    denied = harness.client.post(
        "/api/bot/control", json={"authority": "MANUAL"}
    )
    assert denied.status_code == 403
    assert harness.manager.control_authority == CONTROL_AUTHORITY_BOT
    assert governance_state == before


# =========================
# LONG E2E: FLAT -> BUY -> LONG -> SELL -> FLAT
# =========================

def test_d6_long_cycle_entry_and_close(harness):
    switched = harness.switch_manual()
    assert switched["success"] is True

    preview = harness.preparation()["candidate"]
    approved_preview = preview["quantity"]
    assert preview["notional"] == pytest.approx(POSITION_SIZE_CAP)
    assert preview["requiredMargin"] == pytest.approx(
        POSITION_SIZE_CAP / LEVERAGE
    )

    entry = harness.trade("BUY", "d6-long-entry")
    assert entry["success"] is True
    assert entry["operation"] == MANUAL_OPERATION_ENTRY_LONG
    assert entry["entryAuthority"] == "MANUAL"
    assert entry["mode"] == "paper"
    assert entry["symbol"] == SYMBOL
    assert entry["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert entry["quantityUnit"] == "coin"

    approved = entry["approvedQuantity"]
    executed = entry["quantity"]
    assert approved == pytest.approx(approved_preview)
    assert executed == pytest.approx(approved)
    assert harness.position_state() == "LONG"
    assert harness.engine.pending_order is False

    position = harness.engine.actual_position
    assert position["side"] == "BUY"
    assert position["entry_authority"] == "MANUAL"
    assert position["coin_qty"] == pytest.approx(approved)
    assert harness.portfolio.positions[SYMBOL]["size"] == pytest.approx(approved)
    assert harness.recorder.intents[-1].requested_quantity == pytest.approx(
        approved
    )
    _assert_no_real_order(harness)

    harness.price.price = 101.0
    close = harness.trade("SELL", "d6-long-close")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_LONG
    assert close["closed"] is True
    assert close["closeReason"] == "MANUAL_CLOSE"
    assert close["quantity"] == pytest.approx(approved)
    assert close["positionId"] == entry["positionId"]

    assert harness.engine.actual_position is None
    assert harness.portfolio.positions == {}
    assert harness.position_state() == "FLAT"
    assert harness.engine.pending_order is False
    # No reversal: no opposite position was created.
    assert harness.portfolio.positions.get(SYMBOL) is None
    assert harness.engine.trade_history[-1]["reason"] == "MANUAL_CLOSE"
    assert harness.engine.trade_history[-1]["side"] == "BUY"
    _assert_no_real_order(harness)


# =========================
# SHORT E2E: FLAT -> SELL -> SHORT -> BUY -> FLAT
# =========================

def test_d6_short_cycle_entry_and_close(harness):
    switched = harness.switch_manual()
    assert switched["success"] is True

    entry = harness.trade("SELL", "d6-short-entry")
    assert entry["success"] is True
    assert entry["operation"] == MANUAL_OPERATION_ENTRY_SHORT
    assert entry["entryAuthority"] == "MANUAL"
    assert entry["mode"] == "paper"
    assert entry["symbol"] == SYMBOL
    assert entry["controlAuthority"] == CONTROL_AUTHORITY_MANUAL

    approved = entry["approvedQuantity"]
    executed = entry["quantity"]
    assert executed == pytest.approx(approved)
    assert harness.position_state() == "SHORT"
    assert harness.engine.pending_order is False

    position = harness.engine.actual_position
    assert position["side"] == "SELL"
    assert position["entry_authority"] == "MANUAL"
    assert position["coin_qty"] == pytest.approx(approved)
    assert harness.portfolio.positions[SYMBOL]["size"] == pytest.approx(approved)
    _assert_no_real_order(harness)

    harness.price.price = 99.0
    close = harness.trade("BUY", "d6-short-close")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_SHORT
    assert close["closed"] is True
    assert close["closeReason"] == "MANUAL_CLOSE"
    assert close["quantity"] == pytest.approx(approved)

    assert harness.engine.actual_position is None
    assert harness.portfolio.positions == {}
    assert harness.position_state() == "FLAT"
    assert harness.engine.pending_order is False
    assert harness.portfolio.positions.get(SYMBOL) is None
    assert harness.engine.trade_history[-1]["reason"] == "MANUAL_CLOSE"
    assert harness.engine.trade_history[-1]["side"] == "SELL"
    _assert_no_real_order(harness)


# =========================
# FULL SEQUENCE: LONG THEN SHORT, NO REVERSAL
# =========================

def test_d6_full_sequence_no_reversal(harness):
    assert harness.switch_manual()["success"] is True

    # LONG
    assert harness.trade("BUY", "d6-seq-long-entry")["operation"] == (
        MANUAL_OPERATION_ENTRY_LONG
    )
    assert harness.position_state() == "LONG"
    assert harness.trade("SELL", "d6-seq-long-close")["operation"] == (
        MANUAL_OPERATION_CLOSE_LONG
    )
    assert harness.position_state() == "FLAT"

    # The existing 3s execution cooldown separates two live entries. A human
    # operator waits for it; the E2E waits for it too rather than bypassing it.
    time.sleep(3.1)

    # SHORT
    assert harness.trade("SELL", "d6-seq-short-entry")["operation"] == (
        MANUAL_OPERATION_ENTRY_SHORT
    )
    assert harness.position_state() == "SHORT"
    assert harness.trade("BUY", "d6-seq-short-close")["operation"] == (
        MANUAL_OPERATION_CLOSE_SHORT
    )
    assert harness.position_state() == "FLAT"

    # Exactly two closes, two entries, no reversal anywhere.
    assert len(harness.engine.trade_history) == 2
    assert [record["reason"] for record in harness.engine.trade_history] == [
        "MANUAL_CLOSE",
        "MANUAL_CLOSE",
    ]
    assert harness.portfolio.positions == {}
    assert harness.engine.actual_position is None
    assert harness.engine.pending_order is False
    _assert_no_real_order(harness)


def test_d6_manual_entry_denied_when_control_is_bot(harness):
    denied = harness.client.post(
        "/api/bot/manual-trade",
        json={"action": "BUY", "requestId": "d6-bot-deny",
              "expectedMode": "paper", "expectedSymbol": SYMBOL,
              "expectedControlRevision": harness.manager.control_revision},
        cookies=harness._cookies(),
        headers={CSRF_TOKEN_HEADER: harness.csrf},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["reason"] == "MANUAL_CONTROL_REQUIRED"
    assert harness.engine.actual_position is None
    assert harness.engine.paper_orders == []
