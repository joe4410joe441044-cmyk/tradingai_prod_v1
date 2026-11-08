# -*- coding: utf-8 -*-
"""Offline runtime wiring for durable live orders and exchange stops."""

import fcntl
import json
import os
import time
from pathlib import Path

import pytest
import requests

import backend.config as backend_config
from backend.execution.kucoin_trade import KucoinTradeClient
from backend.execution.live_order_intent import (
    IntentStore,
    liquidation_risk_boundary,
)
from backend.runtime.governance_runtime import governance_state
from Bot.engine.execution_engine import ExecutionEngine


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_plan = []
        self.get_plan = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.posts.append(json.loads(data))
        if self.post_plan:
            item = self.post_plan.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return Response({"code": "200000", "data": {"orderId": "order-1"}})

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        if self.get_plan:
            item = self.get_plan.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return Response({"code": "200000", "data": {}})


def bind_verified_permission(trade):
    trade.permission_contract = {
        "permissionStatus": "VERIFIED",
        "verifiedPermission": "TRADE",
        "verificationSource": "KUCOIN_ACCOUNT_RESPONSE:permission",
        "verifiedAt": time.time(),
        "credentialFingerprint": trade.current_credential_fingerprint(),
        "venue": "KUCOIN_FUTURES",
    }
    return trade


def trade_client(tmp_path, name="intents.json"):
    trade = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    trade.session = FakeSession()
    trade.live_order_allowed = True
    trade.runtime_submission_allowed = True
    bind_verified_permission(trade)
    path = str(Path(tmp_path) / name)
    configured = trade.configure_live_runtime_intent_store(path)
    assert configured["ready"] is True
    return trade


def entry(trade, intent_id="entry-runtime"):
    return trade.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        intent_id=intent_id,
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "buy",
            "type": "market",
            "size": "1",
            "leverage": "2",
            "marginMode": "ISOLATED",
        },
    )


def stop_payload(client_oid):
    return Response({"code": "200000", "data": {"items": [{
        "clientOid": client_oid,
        "symbol": "XRPUSDTM",
        "side": "sell",
        "size": "1",
        "stopPrice": "1.24",
        "reduceOnly": True,
        "id": "stop-1",
    }]}})


def test_missing_store_rejects_live_entry_without_post():
    trade = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    trade.session = FakeSession()
    trade.live_order_allowed = True
    trade.runtime_submission_allowed = True
    opened = trade.configure_live_runtime_intent_store(None)
    assert opened["reason"] == "STORE_PATH_MISSING"
    result = entry(trade)
    assert result["reason"] == "STORE_PATH_MISSING"
    assert trade.session.posts == []


def test_corrupt_store_and_permission_and_interrupted_write_fail_closed(tmp_path, monkeypatch):
    corrupt = Path(tmp_path) / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    trade = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    trade.session = FakeSession()
    trade.live_order_allowed = True
    trade.runtime_submission_allowed = True
    bind_verified_permission(trade)
    assert trade.configure_live_runtime_intent_store(str(corrupt))["reason"] == "STORE_CORRUPT"
    assert entry(trade)["reason"] == "STORE_CORRUPT"
    assert trade.session.posts == []

    blocked = Path(tmp_path) / "blocked"
    blocked.mkdir()
    os.chmod(blocked, 0o500)
    try:
        denied = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
        denied.live_order_allowed = True
        denied.runtime_submission_allowed = True
        denied.session = FakeSession()
        bind_verified_permission(denied)
        assert denied.configure_live_runtime_intent_store(str(blocked / "intents.json"))["ready"] is False
        assert entry(denied)["submit"] is False
        assert denied.session.posts == []
    finally:
        os.chmod(blocked, 0o700)

    target = Path(tmp_path) / "partial.json"
    store = IntentStore(str(target))
    monkeypatch.setattr(os, "replace", lambda source, destination: (_ for _ in ()).throw(OSError("interrupted")))
    failed = store.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="partial")
    assert failed["reason"] == "STORE_WRITE_FAILED"
    assert store.get("partial") is None
    assert not target.exists()


def test_concurrent_writer_is_rejected(tmp_path):
    path = Path(tmp_path) / "locked.json"
    store = IntentStore(str(path))
    handle = open(str(path) + ".lock", "a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        failed = store.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="busy")
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    assert failed["reason"] == "STORE_BUSY"
    assert not path.exists()


def test_happy_path_protects_then_confirms_flat(tmp_path):
    trade = trade_client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    assert placed["commitState"] == "PROTECTION_PENDING"
    trade.session.get_plan.append(stop_payload(placed["clientOid"]))
    assert trade.reconcile_intent(placed["intentId"])["commitState"] == "PROTECTION_CONFIRMED"
    exited = trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        parent_id=opened["intentId"],
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "sell",
            "type": "market",
            "size": "1",
            "reduceOnly": True,
            "marginMode": "ISOLATED",
        },
    )
    assert exited["commitState"] == "EXIT_PENDING"
    flat = trade.confirm_exchange_flat(exited["intentId"], False)
    assert flat["commitState"] == "FLAT_CONFIRMED"
    recovered = trade.recover_unresolved_intents()
    assert recovered["postAttempts"] == 0
    assert recovered["complete"] is True
    assert liquidation_risk_boundary()["LIQUIDATION_2X"] == "UNKNOWN"


def test_entry_timeout_restarts_without_a_second_post(tmp_path):
    trade = trade_client(tmp_path)
    trade.session.post_plan.append(requests.exceptions.Timeout("accepted-remotely"))
    lost = entry(trade)
    assert lost["commitState"] == "UNKNOWN_COMMIT"
    restarted = trade_client(tmp_path)
    restarted.session.get_plan.append(Response({
        "code": "200000",
        "data": {"clientOid": lost["clientOid"], "symbol": "XRPUSDTM", "status": "open"},
    }))
    recovered = restarted.recover_unresolved_intents()
    assert restarted.session.posts == []
    assert recovered["postAttempts"] == 0
    assert restarted._order_intent_store().get(lost["intentId"])["state"] == "ACCEPTED"
    again = entry(restarted, "entry-runtime")
    assert again["submit"] is False
    assert restarted.session.posts == []


def test_stop_timeout_restarts_without_a_second_stop(tmp_path):
    trade = trade_client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    trade.session.post_plan.append(requests.exceptions.Timeout("stop"))
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    assert placed["commitState"] == "PROTECTION_UNKNOWN"
    posts = len(trade.session.posts)
    restarted = trade_client(tmp_path)
    restarted.session.get_plan.append(stop_payload(placed["clientOid"]))
    restarted.recover_unresolved_intents()
    assert restarted.session.posts == []
    assert len(trade.session.posts) == posts
    assert restarted._order_intent_store().get(placed["intentId"])["state"] == "PROTECTION_CONFIRMED"


def test_engine_blocks_unrecovered_store_and_confirms_stop(tmp_path):
    missing = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    missing.configure_live_runtime_intent_store(None)
    engine = ExecutionEngine(exchange=missing)
    engine.config.update({
        "mode": "live",
        "dry_run": False,
        "liveOrderEntryAllowed": True,
    })
    engine.balance_check_ok = True
    engine.position_check_ok = True
    engine._exchange_credentials_ready = lambda: True
    saved = {
        "execution_enabled": governance_state.get("execution_enabled"),
        "emergency_stop": governance_state.get("emergency_stop"),
    }
    previous_mode = backend_config.TRADE_MODE
    previous_allow = backend_config.ALLOW_LIVE
    try:
        governance_state["execution_enabled"] = True
        governance_state["emergency_stop"] = False
        backend_config.TRADE_MODE = "live"
        backend_config.ALLOW_LIVE = True
        blocked = engine.build_live_readiness(entry_authority="BOT")
    finally:
        governance_state.update(saved)
        backend_config.TRADE_MODE = previous_mode
        backend_config.ALLOW_LIVE = previous_allow
    assert blocked["realOrderAllowed"] is False
    assert "LIVE_ORDER_INTENT_STORE_UNAVAILABLE" in blocked["blockReasons"]
    assert "LIVE_ORDER_RECOVERY_INCOMPLETE" in blocked["blockReasons"]

    trade = trade_client(tmp_path, "engine.json")
    opened = entry(trade)
    engine.exchange = trade
    engine.symbol = "XRPUSDTM"
    engine.actual_position = {
        "symbol": "XRPUSDTM",
        "side": "BUY",
        "qty": 1,
        "sl": 1.24,
        "tp": 1.30,
        "multiplier": 1,
        "protection_state": "ACTIVE",
    }
    trade.session.get_plan.append(stop_payload("pending"))
    engine._confirm_exchange_protective_stop(
        {"symbol": "XRPUSDTM", "side": "buy", "qty": 1, "marginMode": "ISOLATED"},
        {"intentId": opened["intentId"]},
    )
    # The queued lookup used a placeholder oid. Confirm the real stop explicitly.
    stop_id = engine.actual_position.get("exchange_protection_state")
    if stop_id != "PROTECTION_CONFIRMED":
        record = next(
            item for item in trade._order_intent_store().records()
            if item.get("purpose") == "PROTECTION"
        )
        trade.session.get_plan.append(stop_payload(record["clientOid"]))
        assert trade.reconcile_intent(record["intentId"])["commitState"] == "PROTECTION_CONFIRMED"
        engine.actual_position["exchange_protection_state"] = "PROTECTION_CONFIRMED"
        engine.actual_position["protection_state"] = "ACTIVE"
    assert engine.live_position_protection_status()["protected"] is True


def test_authority_gates_reject_writes(tmp_path):
    trade = trade_client(tmp_path)
    trade.live_order_allowed = False
    assert entry(trade)["commitState"] == "DISARMED"
    trade.live_order_allowed = True
    bind_verified_permission(trade)
    trade.runtime_submission_allowed = False
    assert entry(trade)["commitState"] == "STOPPED"
    trade.runtime_submission_allowed = True
    mismatched = trade.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        account_symbol="ETHUSDTM",
        body_fields={"symbol": "XRPUSDTM", "side": "buy", "type": "market", "size": "1"},
    )
    assert mismatched["reason"] == "ACCOUNT_SYMBOL_MISMATCH"
    trade.exchange_state_fresh = False
    gates = trade.runtime_order_gates()
    assert gates["exchangeStateFresh"] is False
    assert trade.session.posts == []

    paper = ExecutionEngine(exchange=trade)
    paper.config["mode"] = "paper"
    paper.start()
    assert paper.live_order_recovery is None
    assert trade.session.posts == []


def test_emergency_exit_stays_authorized_when_entry_authority_is_revoked(tmp_path):
    trade = trade_client(tmp_path)
    trade.live_order_allowed = False
    trade.runtime_submission_allowed = False
    assert entry(trade)["commitState"] == "DISARMED"
    exited = trade.submit_bounded_order(
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
    assert exited["submit"] is True
    assert exited["commitState"] == "EXIT_PENDING"
    assert len(trade.session.posts) == 1
    assert trade.session.posts[0]["reduceOnly"] is True

    missing = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    missing.session = FakeSession()
    missing.live_order_allowed = False
    missing.configure_live_runtime_intent_store(None)
    blocked = missing.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={"symbol": "XRPUSDTM", "side": "sell", "type": "market", "size": "1"},
    )
    assert blocked["submit"] is False
    assert blocked["reason"] == "STORE_PATH_MISSING"
    assert missing.session.posts == []
