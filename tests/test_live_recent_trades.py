import json
import time
from unittest.mock import Mock

from backend.market.exchanges.kucoin_market_ws import OrderBookWS
from backend.market.recent_trades import (
    RecentMarketTrades,
    normalize_exchange_timestamp,
)


def trade(*, trade_id="trade-1", symbol="XBTUSDTM", timestamp=None,
          price="100.5", size=2, side="buy", sequence=1):
    return {
        "tradeId": trade_id,
        "symbol": symbol,
        "ts": timestamp if timestamp is not None else int(time.time() * 1_000_000_000),
        "price": price,
        "size": size,
        "side": side,
        "sequence": sequence,
    }


def window(symbol="BTCUSDT", exchange_symbol="XBTUSDTM", maximum=100):
    return RecentMarketTrades(
        symbol=symbol,
        exchange_symbol=exchange_symbol,
        context_key=f"KUCOIN:FUTURES:{exchange_symbol}",
        maximum=maximum,
    )


def test_timestamp_units_are_normalized_without_epoch_corruption():
    now = 1_800_000_000
    assert normalize_exchange_timestamp(now, now=now) == now
    assert normalize_exchange_timestamp(now * 1_000, now=now) == now
    assert normalize_exchange_timestamp(now * 1_000_000, now=now) == now
    assert normalize_exchange_timestamp(now * 1_000_000_000, now=now) == now
    assert normalize_exchange_timestamp("bad", now=now) is None
    assert normalize_exchange_timestamp(now + 301, now=now) is None


def test_buffer_normalizes_orders_deduplicates_and_is_bounded():
    rows = window(maximum=3)
    now = time.time()
    for index in range(5):
        assert rows.append(trade(
            trade_id=f"trade-{index}",
            timestamp=int((now + index) * 1_000_000_000),
            side="buy" if index % 2 else "sell",
            sequence=index,
        ), now=now + 5)
    assert not rows.append(trade(
        trade_id="trade-4",
        timestamp=int((now + 4) * 1_000_000_000),
    ), now=now + 5)
    snapshot = rows.snapshot()
    assert snapshot["ready"] is True
    assert [row["tradeId"] for row in snapshot["rows"]] == [
        "trade-4", "trade-3", "trade-2",
    ]
    assert snapshot["rows"][0]["side"] == "SELL"
    assert snapshot["rows"][0]["price"] == 100.5
    assert snapshot["rows"][0]["quantity"] == 2.0
    assert snapshot["rows"][0]["contextKey"] == "KUCOIN:FUTURES:XBTUSDTM"


def test_malformed_and_wrong_symbol_trades_are_rejected():
    rows = window()
    assert not rows.append(None)
    assert not rows.append(trade(trade_id="", side="buy"))
    assert not rows.append(trade(symbol="ETHUSDTM"))
    assert not rows.append(trade(side="unknown"))
    assert not rows.append(trade(price="nan"))
    assert not rows.append(trade(size=0))
    assert not rows.append(trade(timestamp=1))
    assert rows.snapshot() == {"ready": False, "rows": []}


def test_symbol_windows_isolate_late_old_symbol_events():
    old = window()
    new = window("ETHUSDT", "ETHUSDTM")
    assert old.append(trade())
    assert not new.append(trade())
    assert new.append(trade(trade_id="eth-1", symbol="ETHUSDTM"))
    assert [row["symbol"] for row in new.snapshot()["rows"]] == ["ETHUSDT"]


def test_kucoin_socket_subscribes_and_routes_public_execution_messages():
    client = OrderBookWS("BTCUSDT", Mock(), "runtime")
    websocket = Mock()
    client._start_snapshot_sync = Mock()
    client.on_open(websocket)
    subscriptions = [json.loads(call.args[0]) for call in websocket.send.call_args_list]
    assert [item["topic"] for item in subscriptions] == [
        "/contractMarket/level2:XBTUSDTM",
        "/contractMarket/execution:XBTUSDTM",
    ]
    client.on_message(websocket, json.dumps({
        "type": "ack",
        "id": client._trade_subscription_id,
    }))
    assert client.recent_trades.snapshot()["ready"] is True
    client.on_message(websocket, json.dumps({
        "type": "message",
        "topic": "/contractMarket/execution:XBTUSDTM",
        "data": trade(),
    }))
    assert [row["tradeId"] for row in client.recent_trades.snapshot()["rows"]] == [
        "trade-1",
    ]
    client.on_open(websocket)
    assert client.recent_trades.snapshot() == {"ready": False, "rows": []}


def test_kucoin_trade_stream_fails_closed_on_disconnect_and_error():
    client = OrderBookWS("BTCUSDT", Mock(), "runtime")
    websocket = Mock()
    client._start_snapshot_sync = Mock()
    client.on_open(websocket)
    client.on_message(websocket, json.dumps({
        "type": "ack",
        "id": client._trade_subscription_id,
    }))
    client.on_message(websocket, json.dumps({
        "type": "message",
        "topic": "/contractMarket/execution:XBTUSDTM",
        "data": trade(),
    }))

    client.on_close(websocket, 1006, "connection lost")
    assert client._trade_subscription_id is None
    assert client.recent_trades.snapshot() == {"ready": False, "rows": []}

    client.on_open(websocket)
    client.on_message(websocket, json.dumps({
        "type": "ack",
        "id": client._trade_subscription_id,
    }))
    client.on_error(websocket, RuntimeError("socket failed"))
    assert client._trade_subscription_id is None
    assert client.recent_trades.snapshot() == {"ready": False, "rows": []}
