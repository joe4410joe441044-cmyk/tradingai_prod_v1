# -*- coding: utf-8 -*-
"""WORK AA: runtime-state consistency and private READ contract repair.

All tests are offline.  Fake transports, fake credentials and fake runtime
authorities are used.  No Production credential, intent store, exchange or
service is touched, and no order path is exercised.
"""

import json
import os

import pytest
import requests
from unittest.mock import patch

import backend.config as backend_config
from backend.bot_manager.bot_manager import BotManager
from backend.execution.kucoin_trade import KucoinTradeClient
from backend.execution.kucoin_read_only import (
    STATUS_UNAVAILABLE,
    KucoinReadOnlyVerifier,
    ReadOnlyTransport,
)
from backend.execution.live_order_intent import (
    STORE_PATH_PROTECTED,
    UNKNOWN_COMMIT,
    IntentStore,
    protected_store_conflict,
)
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)
from backend.runtime.runtime_state_contract import (
    CONSISTENT,
    INCONSISTENT,
    MARGIN_MODE_CROSS,
    MARGIN_MODE_ISOLATED,
    PERMISSION_STATUS_UNVERIFIED,
    PERMISSION_STATUS_VERIFIED,
    SNAPSHOT_INCONSISTENT,
    SNAPSHOT_MISSING,
    SNAPSHOT_STALE,
    SNAPSHOT_UNKNOWN,
    SNAPSHOT_VALID,
    UNKNOWN,
    classify_stopped_snapshot,
    project_exchange_client_readiness,
    project_lifecycle_consistency,
    project_margin_mode_contract,
    project_permission_contract,
)


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_governance():
    saved = dict(governance_state)
    governance_state.update({
        "execution_enabled": False,
        "emergency_stop": False,
        "emergency_state": EMERGENCY_READY,
        "emergency_timeline": [],
    })
    yield
    governance_state.clear()
    governance_state.update(saved)


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FailingSession:
    def get(self, url, timeout=None, headers=None, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    def post(self, url=None, **kwargs):
        raise AssertionError("READ_ONLY path must not POST")


def _paper_config():
    return (
        patch(
            "backend.bot_manager.bot_manager.backend_config.TRADE_MODE",
            "paper",
        ),
        patch(
            "backend.bot_manager.bot_manager.backend_config.ALLOW_LIVE",
            False,
        ),
    )


def _stopped_bot(tmp_path):
    bot = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    bot.stopped_paper_durable_snapshot_path = str(
        tmp_path / "stopped_paper_safety_snapshot.json"
    )
    bot.engine = None
    bot.lifecycle_state = "STOPPED"
    bot.loop_state = "STOPPED"
    bot._running = False
    bot.pending_order = False
    return bot


def _recovered_bot(tmp_path):
    bot = _stopped_bot(tmp_path)
    paper, live = _paper_config()
    with paper, live:
        result = bot.refresh_stopped_paper_safety_authority()
    assert result["refreshed"] is True
    return bot


def _account(**changes):
    value = {
        "authenticated": True,
        "connected": True,
        "apiKeyPresent": True,
        "stale": False,
        "balance": 8.0,
        "equity": 8.0,
        "availableBalance": 8.0,
        "balanceSource": "KUCOIN_FUTURES_READ_ONLY",
        "positionSource": "KUCOIN_FUTURES_READ_ONLY",
        "positionSummary": "FLAT",
        "positions": [],
        "permission": "READ_ONLY",
        "permissionClaimed": "READ_ONLY",
        "permissionVerified": False,
        "permissionStatus": "UNVERIFIED",
        "permissionVerificationSource": "NOT_VERIFIED",
        "requiredMarginMode": "ISOLATED",
        "actualMarginMode": "CROSS",
        "marginModeKnown": True,
        "marginModeCompatible": False,
        "marginModeReason": "MARGIN_MODE_MISMATCH",
        "marginModeSource": "KUCOIN_V2_POSITION_MARGIN_MODE",
    }
    value.update(changes)
    return value


# ---------------------------------------------------------------------------
# 1-3: lifecycle / loop / service boundaries
# ---------------------------------------------------------------------------


def test_running_bot_with_stopped_loop_is_explicit_and_not_false_stopped():
    contract = project_lifecycle_consistency(
        bot_lifecycle_state="RUNNING",
        loop_state="STOPPED",
        engine_available=True,
        execution_authority="DISABLED",
    )

    assert contract["state"] == CONSISTENT
    assert contract["consistent"] is True
    assert contract["boundaries"]["botLifecycle"] == "RUNNING"
    assert contract["boundaries"]["tradingLoop"] == "STOPPED"
    assert "BOT_ATTACHED_LOOP_STOPPED" in contract["reasons"]
    assert contract["falseStoppedProjected"] is False


def test_true_stopped_state_is_consistent():
    contract = project_lifecycle_consistency(
        bot_lifecycle_state="STOPPED",
        loop_state="STOPPED",
        engine_available=False,
        execution_authority="DISABLED",
        durable_snapshot_state=SNAPSHOT_VALID,
    )

    assert contract["state"] == CONSISTENT
    assert contract["boundaries"]["botLifecycle"] == "STOPPED"
    assert contract["boundaries"]["tradingLoop"] == "STOPPED"


def test_service_active_is_not_equated_with_bot_running():
    contract = project_lifecycle_consistency(
        service_active=True,
        bot_lifecycle_state="STOPPED",
        loop_state="STOPPED",
        engine_available=False,
    )

    assert contract["boundaries"]["serviceActive"] is True
    assert contract["boundaries"]["botLifecycle"] == "STOPPED"
    assert contract["state"] == CONSISTENT
    assert contract["serviceActiveIsNotBotRunning"] is True


def test_stopped_bot_with_running_loop_is_a_contradiction():
    contract = project_lifecycle_consistency(
        bot_lifecycle_state="STOPPED",
        loop_state="RUNNING",
        engine_available=True,
    )

    assert contract["state"] == INCONSISTENT
    assert "LOOP_RUNNING_WHILE_BOT_STOPPED" in contract["reasons"]


def test_unknown_lifecycle_state_stays_unknown():
    contract = project_lifecycle_consistency(
        bot_lifecycle_state="???",
        loop_state="STOPPED",
    )

    assert contract["state"] == UNKNOWN
    assert contract["consistent"] is None


# ---------------------------------------------------------------------------
# 4-6: durable STOPPED snapshot
# ---------------------------------------------------------------------------


def test_missing_snapshot_is_missing_not_stopped_evidence():
    contract = classify_stopped_snapshot({
        "valid": False,
        "reason": "DURABLE_SNAPSHOT_MISSING",
        "durableExists": False,
    })

    assert contract["state"] == SNAPSHOT_MISSING
    assert contract["usableAsStoppedEvidence"] is False
    assert contract["missingIsStoppedEvidence"] is False


def test_stale_snapshot_is_stale_not_valid():
    contract = classify_stopped_snapshot({
        "valid": False,
        "reason": "DURABLE_SNAPSHOT_STALE",
        "durableExists": True,
    })

    assert contract["state"] == SNAPSHOT_STALE
    assert contract["usableAsStoppedEvidence"] is False
    assert contract["staleIsStoppedEvidence"] is False


def test_contradictory_snapshot_is_inconsistent():
    contract = classify_stopped_snapshot({
        "valid": False,
        "reason": "DURABLE_SNAPSHOT_LIFECYCLE_MISMATCH",
        "durableExists": True,
    })

    assert contract["state"] == SNAPSHOT_INCONSISTENT


def test_unknown_snapshot_reason_is_unknown():
    contract = classify_stopped_snapshot({
        "valid": False,
        "reason": "SOMETHING_NEW",
        "durableExists": True,
    })

    assert contract["state"] == SNAPSHOT_UNKNOWN


def test_restart_recovery_accepts_valid_durable_evidence(tmp_path):
    bot = _recovered_bot(tmp_path)
    status = bot.get_stopped_paper_snapshot_status()

    assert status["snapshotState"] == SNAPSHOT_VALID
    assert status["usableAsStoppedEvidence"] is True
    assert status["valid"] is True
    assert status["durableExists"] is True

    contract = project_lifecycle_consistency(
        bot_lifecycle_state=bot.lifecycle_state,
        loop_state=bot.loop_state,
        engine_available=bot.engine is not None,
        durable_snapshot_state=status["snapshotState"],
    )
    assert contract["state"] == CONSISTENT


def test_missing_snapshot_status_is_exposed_as_missing(tmp_path):
    bot = _stopped_bot(tmp_path)
    status = bot.get_stopped_paper_snapshot_status()

    assert status["snapshotState"] == SNAPSHOT_MISSING
    assert status["usableAsStoppedEvidence"] is False
    assert status["missingIsStoppedEvidence"] is False


def test_stale_snapshot_status_is_exposed_as_stale(tmp_path):
    bot = _recovered_bot(tmp_path)
    bot.stopped_paper_durable_snapshot_max_age = 0.0
    status = bot.get_stopped_paper_snapshot_status()

    assert status["snapshotState"] == SNAPSHOT_STALE
    assert status["usableAsStoppedEvidence"] is False


# ---------------------------------------------------------------------------
# 7-9: margin mode contract
# ---------------------------------------------------------------------------


def test_cross_observed_against_required_isolated_is_mismatch():
    contract = project_margin_mode_contract(
        required_mode=MARGIN_MODE_ISOLATED,
        configured_mode=MARGIN_MODE_ISOLATED,
        effective_mode=MARGIN_MODE_CROSS,
        observed_mode=MARGIN_MODE_CROSS,
        known=True,
    )

    assert contract["state"] == "MISMATCH"
    assert contract["compatible"] is False
    assert contract["reason"] == "MARGIN_MODE_MISMATCH"
    assert contract["crossEqualsIsolated"] is False
    assert contract["autoChangeAllowed"] is False


def test_isolated_confirmed_is_compatible():
    contract = project_margin_mode_contract(
        required_mode=MARGIN_MODE_ISOLATED,
        observed_mode=MARGIN_MODE_ISOLATED,
        known=True,
    )

    assert contract["state"] == "COMPATIBLE"
    assert contract["compatible"] is True


def test_unknown_margin_mode_is_not_coerced():
    contract = project_margin_mode_contract(
        required_mode=MARGIN_MODE_ISOLATED,
        observed_mode=None,
        known=False,
    )

    assert contract["state"] == "UNKNOWN"
    assert contract["compatible"] is None
    assert contract["observedMode"] == "UNKNOWN"


def test_readiness_blocks_known_cross_margin(tmp_path):
    manager = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    manager.engine = None
    manager.config = {"mode": "live", "dry_run": False}
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "STOPPED"
    manager.exchange_client_ready = False
    manager.exchange_auth_ready = True
    manager.balance_check_ok = False
    manager.position_check_ok = False
    manager._get_real_account_snapshot = (
        lambda *args, **kwargs: _account()
    )

    readiness = manager._build_live_readiness_snapshot("live", False)

    assert readiness["marginModeContract"]["state"] == "MISMATCH"
    assert readiness["marginModeContract"]["observedMode"] == "CROSS"
    assert readiness["marginModeContract"]["requiredMode"] == "ISOLATED"
    assert "MARGIN_MODE_MISMATCH" in readiness["blockReasons"]
    assert readiness["realOrderAllowed"] is False


# ---------------------------------------------------------------------------
# 10-13: KuCoin permission / private READ
# ---------------------------------------------------------------------------


@patch("backend.execution.kucoin_trade.requests.Session.get")
def test_hardcoded_read_only_is_not_verified_permission(request_get):
    request_get.return_value = Response({
        "code": "200000",
        "data": {
            "currency": "USDT",
            "accountEquity": "8.0",
            "availableBalance": "7.9",
            "marginBalance": "8.0",
            "positionMargin": "0",
            "orderMargin": "0",
            "unrealisedPNL": "0",
        },
    })
    client = KucoinTradeClient(
        api_key="secret-api-key-value",
        api_secret="secret",
        passphrase="pass",
    )

    overview = client.get_account_overview()

    assert overview["permission"] == "READ_ONLY"
    assert overview["permissionClaimed"] == "READ_ONLY"
    assert overview["permissionVerified"] is False
    assert overview["permissionStatus"] == PERMISSION_STATUS_UNVERIFIED
    assert overview["permissionVerificationSource"] == "NOT_VERIFIED"
    assert overview["permissionVerifiedPermission"] is None
    assert overview["credentialFingerprint"].startswith("sha256:")
    assert "secret-api-key-value" not in json.dumps(overview)


@patch("backend.execution.kucoin_trade.requests.Session.get")
def test_explicit_response_permission_can_be_verified(request_get):
    request_get.return_value = Response({
        "code": "200000",
        "data": {
            "currency": "USDT",
            "accountEquity": "8.0",
            "availableBalance": "7.9",
            "marginBalance": "8.0",
            "permission": "READ_ONLY",
        },
    })
    client = KucoinTradeClient(
        api_key="key",
        api_secret="secret",
        passphrase="pass",
    )

    overview = client.get_account_overview()

    assert overview["permissionVerified"] is True
    assert overview["permissionStatus"] == PERMISSION_STATUS_VERIFIED
    assert overview["permissionVerificationSource"].startswith(
        "KUCOIN_ACCOUNT_RESPONSE:"
    )


def test_private_read_success_does_not_prove_no_trading_permission():
    permission = project_permission_contract(
        claimed_permission="READ_ONLY",
        verified_permission="TRADE",
        verification_source="KUCOIN_ACCOUNT_RESPONSE:permission",
        authenticated=True,
        credential_fingerprint="sha256:abc",
    )
    readiness = project_exchange_client_readiness(
        client_constructed=True,
        credentials_present=True,
        public_read_ok=True,
        authenticated=True,
        permission_contract=permission,
        real_order_allowed=False,
    )

    assert permission["privateReadReady"] is True
    assert permission["tradingPermission"] == "TRADE"
    assert permission["readSuccessImpliesNoTradingPermission"] is False
    assert readiness["privateReadReady"] is True
    assert readiness["realOrderAuthority"] is False
    assert readiness["privateReadImpliesTradingAuthority"] is False


def test_private_read_failure_is_unavailable():
    trade = KucoinTradeClient(
        api_key="key",
        api_secret="secret",
        passphrase="pass",
    )
    transport = ReadOnlyTransport(
        FailingSession(),
        max_retries=0,
        sleep=lambda _seconds: None,
    )
    trade.session = transport
    verifier = KucoinReadOnlyVerifier(trade, transport=transport)

    result = verifier.account_read()

    assert result["status"] == STATUS_UNAVAILABLE


def test_credential_unavailable_is_explicit():
    readiness = project_exchange_client_readiness(
        client_constructed=False,
        credentials_present=False,
        public_read_ok=False,
        authenticated=False,
        permission_contract=project_permission_contract(
            claimed_permission=None,
            authenticated=False,
        ),
        real_order_allowed=False,
    )

    assert readiness["publicReadReady"] is False
    assert readiness["privateReadReady"] is False
    assert readiness["tradingClientReady"] is False
    assert readiness["realOrderAuthority"] is False
    assert "KUCOIN_CREDENTIALS_MISSING" in readiness["reasonCodes"]


# ---------------------------------------------------------------------------
# 14-15: exchange client readiness separation
# ---------------------------------------------------------------------------


def test_public_client_ready_does_not_make_private_client_ready():
    readiness = project_exchange_client_readiness(
        client_constructed=True,
        credentials_present=True,
        public_read_ok=True,
        authenticated=True,
        permission_contract=project_permission_contract(
            claimed_permission="READ_ONLY",
            authenticated=True,
        ),
        real_order_allowed=False,
    )

    assert readiness["publicReadReady"] is True
    assert readiness["privateReadReady"] is False
    assert readiness["tradingClientReady"] is False
    assert readiness["realOrderAuthority"] is False


def test_no_real_order_authority_even_with_private_read():
    permission = project_permission_contract(
        claimed_permission="READ_ONLY",
        verified_permission="READ_ONLY",
        verification_source="KUCOIN_ACCOUNT_RESPONSE:permission",
        authenticated=True,
    )
    readiness = project_exchange_client_readiness(
        client_constructed=True,
        credentials_present=True,
        public_read_ok=True,
        authenticated=True,
        permission_contract=permission,
        real_order_allowed=False,
    )

    assert readiness["privateReadReady"] is True
    assert readiness["realOrderAuthority"] is False
    assert "REAL_ORDER_AUTHORITY_DISABLED" in readiness["reasonCodes"]


def test_readiness_reports_unverified_permission_not_ready(tmp_path):
    manager = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    manager.engine = None
    manager.config = {"mode": "live", "dry_run": False}
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "STOPPED"
    manager.exchange_client_ready = False
    manager.exchange_auth_ready = True
    manager.balance_check_ok = False
    manager.position_check_ok = False
    manager._get_real_account_snapshot = (
        lambda *args, **kwargs: _account()
    )

    readiness = manager._build_live_readiness_snapshot("live", False)
    contract = readiness["exchangeClientReadiness"]

    assert readiness["permissionStatus"] == PERMISSION_STATUS_UNVERIFIED
    assert readiness["permissionVerified"] is False
    assert contract["privateReadReady"] is False
    assert contract["tradingClientReady"] is False
    assert contract["realOrderAuthority"] is False


def test_runtime_lifecycle_contract_is_included_in_readiness(tmp_path):
    manager = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    manager.engine = None
    manager.config = {"mode": "live", "dry_run": False}
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "STOPPED"
    manager._get_real_account_snapshot = (
        lambda *args, **kwargs: _account()
    )

    readiness = manager._build_live_readiness_snapshot("live", False)
    contract = readiness["runtimeStateContract"]

    assert contract["state"] == CONSISTENT
    assert contract["boundaries"]["botLifecycle"] == "RUNNING"
    assert contract["boundaries"]["tradingLoop"] == "STOPPED"


def test_lifecycle_contradiction_fails_closed_in_readiness(tmp_path):
    manager = BotManager(
        saved_mode_path=str(tmp_path / "saved_mode_authority.json"),
    )
    # STOPPED lifecycle with a RUNNING loop is a real contradiction.
    manager.engine = object()
    manager.config = {"mode": "live", "dry_run": False}
    manager.lifecycle_state = "STOPPED"
    manager.loop_state = "RUNNING"
    manager._get_real_account_snapshot = (
        lambda *args, **kwargs: _account()
    )

    readiness = manager._build_live_readiness_snapshot("live", False)

    assert readiness["runtimeStateContract"]["state"] == INCONSISTENT
    assert "RUNTIME_LIFECYCLE_INCONSISTENT" in readiness["blockReasons"]


# ---------------------------------------------------------------------------
# 16-18: preserved intent isolation / UNKNOWN_COMMIT / protective stop
# ---------------------------------------------------------------------------


def test_intent_store_isolation_still_rejects_protected_path(tmp_path, monkeypatch):
    protected = tmp_path / "logs" / "runtime" / "live_order_intents.json"
    protected.parent.mkdir(parents=True)
    protected.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(
        "TRADINGAI_LIVE_ORDER_INTENT_PROTECTED_PATHS",
        json.dumps([str(protected)]),
    )

    assert protected_store_conflict(str(protected)) == STORE_PATH_PROTECTED

    client = KucoinTradeClient(
        api_key="key",
        api_secret="secret",
        passphrase="pass",
    )
    opened = client.configure_live_runtime_intent_store(str(protected))
    assert opened["ready"] is False
    assert opened["reason"] == STORE_PATH_PROTECTED


def test_unknown_commit_state_preserved():
    assert UNKNOWN_COMMIT == "UNKNOWN_COMMIT"
    client = KucoinTradeClient(
        api_key="key",
        api_secret="secret",
        passphrase="pass",
    )
    assert hasattr(client, "place_exchange_protective_stop")
    assert hasattr(client, "reconcile_intent")
    assert hasattr(client, "recover_unresolved_intents")


def test_durable_intent_store_write_contract_preserved(tmp_path):
    store = IntentStore(str(tmp_path / "intents.json"))
    begun = store.begin(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        intent_id="repair-check",
    )
    assert begun["state"] == "INTENT_RECORDED"
    assert store.get("repair-check")["state"] == "INTENT_RECORDED"
