# -*- coding: utf-8 -*-
"""Offline fake-transport coverage for exchange stops and durable order intents."""

import json
import time
from pathlib import Path

import pytest
import requests

from backend.execution.kucoin_trade import KucoinTradeClient
from backend.execution.live_order_intent import (
    FLAT_CONFIRMED,
    INTENT_RECORDED,
    PROTECTION_CONFIRMED,
    PROTECTION_PENDING,
    PROTECTION_UNKNOWN,
    RECONCILIATION_REQUIRED,
    UNKNOWN_COMMIT,
    UNPROTECTED,
    client_oid_for,
    liquidation_risk_boundary,
    quantize_stop_price,
)


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


def client(tmp_path):
    trade = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    trade.live_order_allowed = True
    trade.runtime_submission_allowed = True
    trade.permission_contract = {
        "permissionStatus": "VERIFIED",
        "verifiedPermission": "TRADE",
        "verificationSource": "KUCOIN_ACCOUNT_RESPONSE:permission",
        "verifiedAt": time.time(),
        "credentialFingerprint": trade.current_credential_fingerprint(),
        "venue": "KUCOIN_FUTURES",
    }
    trade.order_intent_path = str(Path(tmp_path) / "intents.json")
    trade.session = FakeSession()
    return trade


def entry(trade, intent_id="entry-1", size=1):
    return trade.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=size,
        intent_id=intent_id,
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "buy",
            "type": "market",
            "size": str(size),
            "leverage": "2",
            "marginMode": "ISOLATED",
        },
    )


def test_unique_client_oid_generation():
    first = client_oid_for("one")
    second = client_oid_for("two")
    assert first != second
    assert first.startswith("ta")
    assert len(first) <= 40
    assert first.isalnum()


def test_durable_intent_before_post(tmp_path):
    trade = client(tmp_path)
    seen = {}

    def post(url, headers=None, data=None, timeout=None):
        store = trade._order_intent_store()
        seen["record"] = store.get("entry-1")
        trade.session.posts.append(json.loads(data))
        return Response({"code": "200000", "data": {"orderId": "order-1"}})

    trade.session.post = post
    entry(trade)
    assert seen["record"]["state"] == INTENT_RECORDED
    assert seen["record"]["clientOid"]


def test_same_intent_retains_client_oid(tmp_path):
    trade = client(tmp_path)
    first = entry(trade)
    trade2 = client(tmp_path)
    store = trade._order_intent_store()
    store.mark(first["intentId"], INTENT_RECORDED)
    trade2._live_order_intent_store = None
    trade2.order_intent_path = trade.order_intent_path
    again = entry(trade2)
    assert again["clientOid"] == first["clientOid"]
    assert again["commitState"] == UNKNOWN_COMMIT
    assert trade2.session.posts == []


def test_different_intents_never_share_client_oid(tmp_path):
    trade = client(tmp_path)
    first = entry(trade, "entry-1")
    store = trade._order_intent_store()
    store.mark(first["intentId"], "FLAT_CONFIRMED")
    second = entry(trade, "entry-2")
    assert first["clientOid"] != second["clientOid"]


def test_post_timeout_after_exchange_acceptance_is_unknown(tmp_path):
    trade = client(tmp_path)
    trade.session.post_plan.append(requests.exceptions.Timeout("accepted-then-lost"))
    result = entry(trade)
    assert result["commitState"] == UNKNOWN_COMMIT
    assert len(trade.session.posts) == 1


def test_lost_acknowledgement_does_not_repost(tmp_path):
    trade = client(tmp_path)
    trade.session.post_plan.append(requests.exceptions.ConnectionError("dropped"))
    entry(trade)
    again = entry(trade)
    assert again["submit"] is False
    assert again["commitState"] == UNKNOWN_COMMIT
    assert len(trade.session.posts) == 1


def test_ambiguous_5xx_is_unknown(tmp_path):
    trade = client(tmp_path)
    trade.session.post_plan.append(Response({"code": "200000"}, status=503))
    result = entry(trade)
    assert result["commitState"] == UNKNOWN_COMMIT
    assert entry(trade)["submit"] is False


def test_delayed_exchange_lookup(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], UNKNOWN_COMMIT)
    trade.session.get_plan.append(requests.exceptions.Timeout("lookup"))
    first = trade.reconcile_intent(opened["intentId"])
    assert first["commitState"] == UNKNOWN_COMMIT
    trade.session.get_plan.append(Response({
        "code": "200000",
        "data": {"clientOid": opened["clientOid"], "symbol": "XRPUSDTM", "status": "open", "id": "ex-1"},
    }))
    second = trade.reconcile_intent(opened["intentId"])
    assert second["commitState"] == "ACCEPTED"


def test_initial_not_found_then_found(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], UNKNOWN_COMMIT)
    trade.session.get_plan.append(Response({"code": "100001", "msg": "order not exist"}))
    missing = trade.reconcile_intent(opened["intentId"])
    assert missing["reason"] == "NOT_FOUND_INCONCLUSIVE"
    trade.session.get_plan.append(Response({
        "code": "200000",
        "data": {"clientOid": opened["clientOid"], "symbol": "XRPUSDTM", "status": "done", "id": "ex-2"},
    }))
    found = trade.reconcile_intent(opened["intentId"])
    assert found["commitState"] == "FILLED"


def test_persistent_unknown_state(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], UNKNOWN_COMMIT)
    trade.session.get_plan.extend([
        Response({"code": "100001", "msg": "order not exist"}),
        Response({"code": "100001", "msg": "order not exist"}),
        Response({"code": "100001", "msg": "order not exist"}),
    ])
    last = None
    for _ in range(3):
        last = trade.reconcile_intent(opened["intentId"])
    assert last["commitState"] == RECONCILIATION_REQUIRED
    assert entry(trade, "entry-other")["submit"] is False
    assert len(trade.session.posts) == 1


def test_restart_with_unresolved_entry_does_not_repost(tmp_path):
    trade = client(tmp_path)
    trade.session.post_plan.append(requests.exceptions.Timeout("lost"))
    opened = entry(trade)
    restarted = client(tmp_path)
    restarted.order_intent_path = trade.order_intent_path
    restarted._live_order_intent_store = None
    again = restarted.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        intent_id=opened["intentId"],
        body_fields={"symbol": "XRPUSDTM", "side": "buy", "type": "market", "size": "1", "leverage": "2", "marginMode": "ISOLATED"},
    )
    assert again["submit"] is False
    assert again["commitState"] == UNKNOWN_COMMIT
    assert restarted.session.posts == []


def test_partial_fill_protection_uses_filled_quantity(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade, size=2)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    body = trade.session.posts[-1]
    assert body["size"] == "1"
    assert body["reduceOnly"] is True
    assert placed["commitState"] == PROTECTION_PENDING


@pytest.mark.parametrize("position_side,stop_price,expected", [
    ("buy", "1.1688831", "1.16889"),
    ("sell", "1.1924969", "1.19249"),
])
def test_stop_price_is_quantized_to_tick(position_side, stop_price, expected):
    close_side = "sell" if position_side == "buy" else "buy"
    assert quantize_stop_price(stop_price, "0.00001", close_side) == expected


def test_stop_price_not_tick_conformant_without_quantization():
    from decimal import Decimal

    assert Decimal("1.1688831") % Decimal("0.00001") != 0


def test_protective_stop_body_uses_tick_conformant_price(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.1688831",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
        tick_size="0.00001",
    )
    body = trade.session.posts[-1]
    from decimal import Decimal

    assert Decimal(body["stopPrice"]) % Decimal("0.00001") == 0
    assert Decimal(body["stopPrice"]) == Decimal("1.16889")
    assert placed["commitState"] == PROTECTION_PENDING


def test_stop_placement_success_requires_exchange_confirmation(tmp_path):
    trade = client(tmp_path)
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
    assert placed["commitState"] == PROTECTION_PENDING
    trade.session.get_plan.append(Response({
        "code": "200000",
        "data": {"items": [{
            "clientOid": placed["clientOid"],
            "symbol": "XRPUSDTM",
            "side": "sell",
            "size": "1",
            "stopPrice": "1.24",
            "reduceOnly": True,
            "id": "stop-1",
        }]},
    }))
    confirmed = trade.reconcile_intent(placed["intentId"])
    assert confirmed["commitState"] == PROTECTION_CONFIRMED


def test_stop_placement_timeout(tmp_path):
    trade = client(tmp_path)
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
    assert placed["commitState"] == PROTECTION_UNKNOWN
    assert len(trade.session.posts) == 2


def test_stop_rejected_is_unprotected(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    trade.session.post_plan.append(Response({"code": "300000", "msg": "rejected"}))
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    assert placed["commitState"] == UNPROTECTED


def test_stop_missing_after_confirmation(tmp_path):
    trade = client(tmp_path)
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
    trade._order_intent_store().mark(placed["intentId"], PROTECTION_CONFIRMED)
    trade.session.get_plan.append(Response({"code": "200000", "data": {"items": []}}))
    missing = trade.reconcile_intent(placed["intentId"])
    assert missing["commitState"] == PROTECTION_UNKNOWN
    assert trade.session.posts[-1]["clientOid"] == placed["clientOid"]


def test_duplicate_stop_prevention(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    kwargs = dict(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    trade.place_exchange_protective_stop(**kwargs)
    second = trade.place_exchange_protective_stop(**kwargs)
    assert second["submit"] is False
    assert len([post for post in trade.session.posts if post.get("stop")]) == 1


def test_unprotected_position_blocks_entry(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], UNPROTECTED)
    blocked = entry(trade, "entry-2")
    assert blocked["submit"] is False
    assert blocked["reason"] == "ENTRY_BLOCKED"


def test_restart_between_fill_and_protection_posts_stop_once(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    restarted = client(tmp_path)
    restarted.order_intent_path = trade.order_intent_path
    restarted._live_order_intent_store = None
    placed = restarted.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    assert placed["submit"] is True
    assert len(restarted.session.posts) == 1
    again = restarted.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
    )
    assert again["submit"] is False


def test_reduce_only_exit_timeout(tmp_path):
    trade = client(tmp_path)
    trade.session.post_plan.append(requests.exceptions.Timeout("exit"))
    result = trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={"symbol": "XRPUSDTM", "side": "sell", "type": "market", "size": "1", "reduceOnly": True, "marginMode": "ISOLATED"},
    )
    assert result["commitState"] == UNKNOWN_COMMIT
    assert trade.session.posts[0]["reduceOnly"] is True
    assert trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={"symbol": "XRPUSDTM", "side": "sell", "type": "market", "size": "1", "reduceOnly": True, "marginMode": "ISOLATED"},
    )["submit"] is False


def test_exit_reconciliation_and_flat_confirmation(tmp_path):
    trade = client(tmp_path)
    opened = trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={"symbol": "XRPUSDTM", "side": "sell", "type": "market", "size": "1", "reduceOnly": True, "marginMode": "ISOLATED"},
    )
    trade.session.get_plan.append(Response({
        "code": "200000",
        "data": {"clientOid": opened["clientOid"], "symbol": "XRPUSDTM", "status": "done", "id": "exit-1"},
    }))
    reconciled = trade.reconcile_intent(opened["intentId"])
    assert reconciled["commitState"] == "FILLED"
    assert trade.confirm_exchange_flat(opened["intentId"], True)["commitState"] == "EXIT_PENDING"
    assert trade.confirm_exchange_flat(opened["intentId"], False)["commitState"] == FLAT_CONFIRMED


def test_exchange_flat_is_not_implied_by_exit_ack(tmp_path):
    trade = client(tmp_path)
    opened = trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={"symbol": "XRPUSDTM", "side": "sell", "type": "market", "size": "1", "reduceOnly": True, "marginMode": "ISOLATED"},
    )
    assert opened["commitState"] == "EXIT_PENDING"
    assert opened["commitState"] != FLAT_CONFIRMED


def test_disarmed_rejects_writes(tmp_path):
    trade = client(tmp_path)
    trade.live_order_allowed = False
    result = entry(trade)
    assert result["commitState"] == "DISARMED"
    assert trade.session.posts == []
    stop = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.24",
        margin_mode="ISOLATED",
        parent_intent_id="missing",
    )
    assert stop["commitState"] == "DISARMED"


def test_stopped_rejects_unauthorized_submission(tmp_path):
    trade = client(tmp_path)
    trade.runtime_submission_allowed = False
    result = entry(trade)
    assert result["commitState"] == "STOPPED"
    assert trade.session.posts == []


def test_account_symbol_mismatch_rejected(tmp_path):
    trade = client(tmp_path)
    result = trade.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        account_symbol="ETHUSDTM",
        body_fields={"symbol": "XRPUSDTM", "side": "buy", "type": "market", "size": "1", "leverage": "2", "marginMode": "ISOLATED"},
    )
    assert result["reason"] == "ACCOUNT_SYMBOL_MISMATCH"
    assert trade.session.posts == []


def test_no_duplicate_order_after_restart(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    restarted = client(tmp_path)
    restarted.order_intent_path = trade.order_intent_path
    restarted._live_order_intent_store = None
    again = restarted.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        intent_id=opened["intentId"],
        body_fields={"symbol": "XRPUSDTM", "side": "buy", "type": "market", "size": "1", "leverage": "2", "marginMode": "ISOLATED"},
    )
    assert again["submit"] is False
    assert restarted.session.posts == []


def test_no_silent_local_only_protection_fallback(tmp_path):
    trade = client(tmp_path)
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
    assert placed["commitState"] != PROTECTION_CONFIRMED
    boundary = liquidation_risk_boundary()
    assert boundary["LIQUIDATION_2X"] == "UNKNOWN"
    assert boundary["LIQUIDATION_3X"] == "UNKNOWN"
    assert boundary["ready"] is False
    assert trade.liquidation_risk_status() == boundary


def test_persisted_intent_is_not_sent_when_restart_is_disarmed(tmp_path):
    trade = client(tmp_path)
    store = trade._order_intent_store()
    record = store.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="held")
    assert record["state"] == INTENT_RECORDED
    restarted = client(tmp_path)
    restarted.order_intent_path = trade.order_intent_path
    restarted.live_order_allowed = False
    restarted._live_order_intent_store = None
    result = restarted.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        intent_id="held",
        body_fields={"symbol": "XRPUSDTM", "side": "buy", "type": "market", "size": "1", "leverage": "2", "marginMode": "ISOLATED"},
    )
    assert result["commitState"] == "DISARMED"
    assert restarted.session.posts == []


def test_stop_invalid_tick_fails_closed_before_post(tmp_path):
    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    posts_before = len(trade.session.posts)
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price="1.1688831",
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
        tick_size="not-a-tick",
    )
    assert placed["commitState"] == UNPROTECTED
    assert placed["reason"] == "STOP_CONTRACT_UNAVAILABLE"
    assert len(trade.session.posts) == posts_before


@pytest.mark.parametrize("stop_price", ["1.23000", "1.23001"])
def test_stop_tick_boundary_is_conformant(tmp_path, stop_price):
    from decimal import Decimal

    trade = client(tmp_path)
    opened = entry(trade)
    trade._order_intent_store().mark(opened["intentId"], "FILLED")
    placed = trade.place_exchange_protective_stop(
        symbol="XRPUSDTM",
        position_side="buy",
        filled_qty=1,
        stop_price=stop_price,
        margin_mode="ISOLATED",
        parent_intent_id=opened["intentId"],
        tick_size="0.00001",
    )
    body = trade.session.posts[-1]
    assert Decimal(body["stopPrice"]) % Decimal("0.00001") == 0
    assert placed["commitState"] == PROTECTION_PENDING
