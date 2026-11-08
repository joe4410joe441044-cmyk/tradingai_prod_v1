# -*- coding: utf-8 -*-
"""WORK AA: LIVE ARM / entry permission fail-closed regression.

Every test is offline.  No exchange request, no real order, no LIVE runtime,
no ARM of a real account.  Fake transport / fake clock / fake permission
evidence are used to prove that REAL order authority cannot be established or
used without current, bound, authoritative trading-permission evidence.
"""

import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend import config as backend_config
from backend.bot_manager.bot_manager import BotManager
from backend.execution.kucoin_trade import KucoinTradeClient
from backend.runtime.governance_runtime import EMERGENCY_READY, governance_state
from backend.runtime.runtime_state_contract import (
    PERMISSION_REASON_ACCOUNT_MISMATCH,
    PERMISSION_REASON_CREDENTIAL_MISMATCH,
    PERMISSION_REASON_DENIED,
    PERMISSION_REASON_EVIDENCE_MISSING,
    PERMISSION_REASON_EXPIRED,
    PERMISSION_REASON_STALE,
    PERMISSION_REASON_UNVERIFIED,
    PERMISSION_REASON_VENUE_MISMATCH,
    evaluate_trading_permission_authority,
    project_permission_contract,
)
from Bot.engine.execution_engine import ExecutionEngine


FP = "sha256:work-aa-permission-test"
NOW = time.time()


def permission_snapshot(**overrides):
    snapshot = {
        "accountType": "KUCOIN_FUTURES",
        "permission": "READ_ONLY",
        "permissionClaimed": "READ_ONLY",
        "permissionVerifiedPermission": "TRADE",
        "permissionVerificationSource": "KUCOIN_ACCOUNT_RESPONSE:permission",
        "permissionVerifiedAt": NOW,
        "permissionVenue": "KUCOIN_FUTURES",
        "credentialFingerprint": FP,
    }
    snapshot.update(overrides)
    return snapshot


def verified_contract(**overrides):
    contract = {
        "permissionStatus": "VERIFIED",
        "verifiedPermission": "TRADE",
        "verificationSource": "KUCOIN_ACCOUNT_RESPONSE:permission",
        "verifiedAt": NOW,
        "credentialFingerprint": FP,
        "venue": "KUCOIN_FUTURES",
    }
    contract.update(overrides)
    return contract


class FakeExchange:
    def __init__(self, contract=None, fingerprint=FP):
        self.api_key = "key"
        self.api_secret = "secret"
        self.passphrase = "passphrase"
        self.permission_contract = dict(contract or {})
        self._fingerprint = fingerprint
        self.order_calls = []
        self._account = {}

    def current_credential_fingerprint(self):
        return self._fingerprint

    def get_account_overview(self):
        return dict(self._account)

    def get_positions(self, *args, **kwargs):
        return None

    def set_live_order_gate(self, *args, **kwargs):
        return None

    def place_order(self, **kwargs):
        self.order_calls.append(kwargs)
        return {"success": True, "order_id": "offline-1", "raw": {}}


@contextmanager
def live_globals(execution_enabled=True):
    previous = dict(governance_state)
    try:
        governance_state.update({
            "execution_enabled": execution_enabled,
            "emergency_stop": False,
            "emergency_state": EMERGENCY_READY,
            "control_authority": "BOT",
            "control_revision": 0,
        })
        with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
            backend_config, "TRADE_MODE", "live"
        ):
            yield
    finally:
        governance_state.clear()
        governance_state.update(previous)


def make_engine(snapshot=None, *, contract=None, mode="live", fingerprint=FP):
    exchange = FakeExchange(contract=contract, fingerprint=fingerprint)
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=SimpleNamespace(initial_balance=1000, balance=1000),
    )
    engine.mode = mode
    engine.symbol = "XRPUSDT"
    engine.status = "RUNNING"
    engine.price_ready = True
    engine.latest_price = 100
    engine.config["mode"] = mode
    engine.config["dry_run"] = mode != "live"
    engine.config["liveOrderEntryAllowed"] = False
    engine.config["realOrderAllowed"] = False
    engine.config["executionEntryAllowed"] = False
    engine.balance_check_ok = True
    engine.position_check_ok = True
    engine.real_balance = 1000
    engine.real_equity = 1000
    engine.real_position = None
    engine.real_position_state = "FLAT"
    engine.actual_position = None
    engine.real_account_snapshot = dict(snapshot or {})
    engine.get_price = lambda: 100
    return engine


def assert_arm_denied(engine, reason=None):
    result = engine.set_live_order_entry_authority(True)
    assert result["success"] is False
    assert result["armed"] is False
    assert result["liveOrderEntryAllowed"] is False
    assert result["realOrderAllowed"] is False
    if reason is not None:
        assert reason in (result.get("blockReasons") or []), result
        assert result.get("reason") == reason
    assert engine.config.get("liveOrderEntryAllowed") is not True


# ---------------------------------------------------------------------------
# ARM permission fail-closed
# ---------------------------------------------------------------------------

def test_unverified_permission_denies_arm():
    engine = make_engine(permission_snapshot(
        permissionVerifiedPermission=None,
        permissionVerificationSource="NOT_VERIFIED",
    ))
    with live_globals():
        assert_arm_denied(engine, PERMISSION_REASON_UNVERIFIED)


def test_unknown_permission_denies_arm_contract():
    authority = evaluate_trading_permission_authority(
        {"permissionStatus": "UNKNOWN"},
        expected_venue="KUCOIN_FUTURES",
        expected_credential_fingerprint=FP,
        now=NOW,
    )
    assert authority["allowed"] is False
    assert authority["reason"] in {
        "TRADING_PERMISSION_UNKNOWN",
        "TRADING_PERMISSION_EVIDENCE_MISSING",
    }


def test_denied_permission_denies_arm():
    engine = make_engine(permission_snapshot(
        permissionVerifiedPermission="DENIED",
        permissionVerificationSource="KUCOIN_ACCOUNT_RESPONSE:permission",
    ))
    with live_globals():
        assert_arm_denied(engine, PERMISSION_REASON_DENIED)


def test_missing_permission_evidence_denies_arm():
    authority = evaluate_trading_permission_authority(
        None,
        expected_venue="KUCOIN_FUTURES",
        expected_credential_fingerprint=FP,
        now=NOW,
    )
    assert authority["allowed"] is False
    assert authority["reason"] == PERMISSION_REASON_EVIDENCE_MISSING

    engine = make_engine({})
    with live_globals():
        result = engine.set_live_order_entry_authority(True)
    assert result["success"] is False
    assert result["armed"] is False


def test_expired_permission_denies_arm():
    engine = make_engine(permission_snapshot(permissionExpiresAt=NOW - 1))
    with live_globals():
        assert_arm_denied(engine, PERMISSION_REASON_EXPIRED)


def test_account_mismatch_denies_arm():
    engine = make_engine(permission_snapshot(
        permissionAccountId="account-A",
        accountId="account-B",
    ))
    with live_globals():
        assert_arm_denied(engine, PERMISSION_REASON_ACCOUNT_MISMATCH)


def test_venue_mismatch_denies_arm():
    engine = make_engine(permission_snapshot(
        permissionVenue="BYBIT_FUTURES",
    ))
    with live_globals():
        assert_arm_denied(engine, PERMISSION_REASON_VENUE_MISMATCH)


def test_credential_mismatch_denies_arm():
    engine = make_engine(
        permission_snapshot(credentialFingerprint="sha256:different"),
        fingerprint=FP,
    )
    with live_globals():
        assert_arm_denied(engine, PERMISSION_REASON_CREDENTIAL_MISMATCH)


def test_verified_bound_evidence_allows_policy_consistent_arm():
    engine = make_engine(permission_snapshot())
    with live_globals():
        result = engine.set_live_order_entry_authority(True)
    assert result["success"] is True
    assert result["armed"] is True
    assert result["realOrderAllowed"] is True
    assert engine.config["liveOrderEntryAllowed"] is True


def test_manager_arm_denies_unverified_permission():
    engine = make_engine(permission_snapshot(
        permissionVerifiedPermission=None,
        permissionVerificationSource="NOT_VERIFIED",
    ))
    manager = BotManager()
    manager.config = {"mode": "live", "dry_run": False}
    manager.engine = engine
    manager.get_authoritative_pending_order_state = lambda: {
        "known": True,
        "pending": False,
        "safe": True,
        "reason": "NO_PENDING_ORDER",
    }
    with live_globals():
        result = manager.set_live_order_entry_authority(True)
    assert result["success"] is False
    assert result["armed"] is False
    assert result["realOrderAllowed"] is False
    assert manager.config.get("liveOrderEntryAllowed") is not True


# ---------------------------------------------------------------------------
# Execution-boundary fail-closed
# ---------------------------------------------------------------------------

class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, headers=None, data=None, timeout=None):
        import json

        self.posts.append(json.loads(data))

        class Response:
            status_code = 200

            def json(self):
                return {"code": "200000", "data": {"orderId": "offline-order"}}

        return Response()


class FakeClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def make_trade(tmp_path, contract, *, live=True):
    trade = KucoinTradeClient(
        api_key="key", api_secret="secret", passphrase="pass"
    )
    trade.session = FakeSession()
    trade.live_order_allowed = live
    trade.runtime_submission_allowed = True
    trade.permission_contract = dict(contract)
    assert trade.configure_live_runtime_intent_store(
        str(Path(tmp_path) / "intents.json")
    )["ready"] is True
    return trade


def submit_entry(trade):
    return trade.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "buy",
            "type": "market",
            "size": "1",
            "leverage": "2",
            "marginMode": "ISOLATED",
        },
    )


def test_direct_execution_bypass_with_missing_evidence_is_denied(tmp_path):
    trade = make_trade(tmp_path, {})
    result = submit_entry(trade)
    assert result["submit"] is False
    assert result["reason"] == PERMISSION_REASON_EVIDENCE_MISSING
    assert trade.session.posts == []


def test_direct_execution_bypass_with_stale_evidence_is_denied(tmp_path):
    contract = verified_contract(verifiedAt=NOW - 3600)
    trade = make_trade(tmp_path, contract)
    result = submit_entry(trade)
    assert result["submit"] is False
    assert result["reason"] == PERMISSION_REASON_STALE
    assert trade.session.posts == []


def test_verified_bound_evidence_allows_entry(tmp_path):
    trade = make_trade(tmp_path, verified_contract())
    trade.permission_contract["credentialFingerprint"] = (
        trade.current_credential_fingerprint()
    )
    result = submit_entry(trade)
    assert result["submit"] is True
    assert len(trade.session.posts) == 1


def test_stale_persisted_arm_denies_entry():
    engine = make_engine(permission_snapshot(permissionVerifiedAt=NOW - 3600))
    engine.config.update({
        "liveOrderEntryAllowed": True,
        "realOrderAllowed": True,
        "executionEntryAllowed": True,
    })
    with live_globals():
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False
    assert PERMISSION_REASON_STALE in engine.last_live_block_reasons


def test_restart_does_not_restore_stale_arm():
    engine = make_engine(permission_snapshot(permissionVerifiedAt=NOW - 3600))
    engine.config.update({
        "liveOrderEntryAllowed": True,
        "realOrderAllowed": True,
        "executionEntryAllowed": True,
    })
    engine.exchange._account = permission_snapshot(
        permissionVerifiedAt=NOW - 3600
    )
    engine.start()
    assert engine.config["liveOrderEntryAllowed"] is False
    assert engine.config["realOrderAllowed"] is False
    assert engine.config["executionEntryAllowed"] is False
    with live_globals():
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False


def test_manual_entry_bypass_is_denied_without_valid_permission():
    engine = make_engine(permission_snapshot(
        permissionVerifiedPermission=None,
        permissionVerificationSource="NOT_VERIFIED",
    ))
    engine.config.update({
        "liveOrderEntryAllowed": True,
        "realOrderAllowed": True,
        "executionEntryAllowed": True,
    })
    with live_globals(execution_enabled=False):
        allowed = engine._live_order_allowed({
            "entryAuthority": "MANUAL",
            "governanceDecision": {"allowed": True},
        })
    assert allowed is False


def test_arm_disarm_race_blocks_entry_when_permission_invalid():
    engine = make_engine(permission_snapshot())
    with live_globals():
        assert engine.set_live_order_entry_authority(True)["success"] is True
        # Permission evidence becomes invalid while the runtime stays armed.
        engine.real_account_snapshot = permission_snapshot(
            permissionExpiresAt=NOW - 1
        )
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False
        engine.set_live_order_entry_authority(False)
        assert engine.config["liveOrderEntryAllowed"] is False
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False


def test_permission_expiry_during_execution_is_denied_with_fake_clock():
    engine = make_engine(permission_snapshot(permissionExpiresAt=NOW + 60))
    engine.config.update({
        "liveOrderEntryAllowed": True,
        "realOrderAllowed": True,
        "executionEntryAllowed": True,
    })
    with live_globals():
        before = engine.build_live_readiness(now=NOW + 1)
        after = engine.build_live_readiness(now=NOW + 120)
    assert before["realOrderAllowed"] is True
    assert after["realOrderAllowed"] is False
    assert PERMISSION_REASON_EXPIRED in after["blockReasons"]


def test_paper_readiness_is_unaffected_by_live_permission_evidence():
    engine = make_engine({}, mode="paper")
    readiness = engine.build_live_readiness(now=NOW)
    assert "TRADING_PERMISSION_UNVERIFIED" not in readiness["blockReasons"]
    assert "TRADING_PERMISSION_EVIDENCE_MISSING" not in readiness["blockReasons"]


def test_protective_stop_and_exit_are_not_blocked_by_missing_entry_permission(tmp_path):
    trade = make_trade(tmp_path, {})
    exit_result = trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "sell",
            "type": "market",
            "size": "1",
            "reduceOnly": True,
            "marginMode": "ISOLATED",
        },
    )
    assert exit_result["submit"] is True
    stop_result = trade.submit_bounded_order(
        purpose="PROTECTION",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        stop_price="1.24",
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "sell",
            "type": "market",
            "size": "1",
            "stopPrice": "1.24",
            "reduceOnly": True,
            "marginMode": "ISOLATED",
        },
    )
    assert stop_result["submit"] is True
    assert len(trade.session.posts) == 2


def test_raw_verified_label_without_trading_permission_is_insufficient():
    contract = project_permission_contract(
        claimed_permission="READ_ONLY",
        verified_permission="READ_ONLY",
        verification_source="KUCOIN_ACCOUNT_RESPONSE:permission",
        verified_at=NOW,
        credential_fingerprint=FP,
        authenticated=True,
        venue="KUCOIN_FUTURES",
    )
    authority = evaluate_trading_permission_authority(
        contract,
        expected_venue="KUCOIN_FUTURES",
        expected_credential_fingerprint=FP,
        now=NOW,
    )
    assert authority["allowed"] is False
    assert authority["reason"] == "TRADING_PERMISSION_EVIDENCE_INCONSISTENT"


def test_manager_readiness_projection_matches_runtime_permission_authority():
    engine = make_engine(permission_snapshot(
        permissionVerifiedPermission=None,
        permissionVerificationSource="NOT_VERIFIED",
    ))
    manager = BotManager()
    manager.config = {"mode": "live", "dry_run": False}
    manager.engine = engine
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "STOPPED"
    manager._running = True
    readiness = manager._build_live_readiness_snapshot("live", False)
    assert readiness["realOrderAllowed"] is False
    assert "TRADING_PERMISSION_UNVERIFIED" in readiness["blockReasons"]
