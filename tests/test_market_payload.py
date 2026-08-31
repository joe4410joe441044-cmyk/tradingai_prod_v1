import asyncio
import time
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from fastapi import WebSocketDisconnect

from backend.api.websocket import websocket_endpoint
from backend.bot_manager.bot_manager import BotManager
from backend.market.exchanges.kucoin_market_ws import (
    OrderBookWS as KuCoinFuturesOrderBookWS,
)


class BrowserMarketPayloadTest(unittest.TestCase):

    @staticmethod
    def _synced_kucoin_client():
        client = KuCoinFuturesOrderBookWS(
            symbol="XRPUSDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )
        client.bids = {0.6123: 100.0, 0.6122: 80.0}
        client.asks = {0.6125: 90.0, 0.6126: 70.0}
        client.snapshot_loaded = True
        client.orderbook_initialized = True
        client.is_orderbook_synced = True
        client.snapshot_sequence = 40
        client.last_sequence_end = 41
        return client

    def test_kucoin_callback_exposes_one_formal_scalar_snapshot(self):
        client = self._synced_kucoin_client()
        diff = {
            "sequence_start": 41,
            "sequence_end": 41,
            "side": "buy",
            "price": 0.6123,
            "size": 100.0,
        }

        client._publish_current_book(diff)

        payload = client.on_update.call_args.args[1]
        self.assertEqual(payload["market_type"], "FUTURES")
        self.assertEqual(payload["exchange_symbol"], "XRPUSDTM")
        self.assertEqual(payload["sequence"], 41)
        self.assertEqual(payload["price"], client.last_price)
        self.assertEqual(payload["best_bid"], client.best_bid)
        self.assertEqual(payload["best_ask"], client.best_ask)
        self.assertEqual(payload["spread"], client.spread)
        self.assertEqual(
            payload["spread"],
            payload["best_ask"] - payload["best_bid"],
        )
        self.assertEqual(
            payload["market_timestamp"],
            client.last_price_update,
        )
        book = payload["order_book"]
        self.assertEqual(book["sequence"], payload["sequence"])
        self.assertEqual(book["timestamp"], payload["market_timestamp"])
        self.assertEqual(book["depth"], 2)
        self.assertEqual(book["dataQuality"], "VALID")
        self.assertEqual(book["syncState"], "SYNCED")
        self.assertEqual(
            [level["price"] for level in book["bids"]],
            [0.6123, 0.6122],
        )
        self.assertEqual(
            [level["price"] for level in book["asks"]],
            [0.6125, 0.6126],
        )

    def test_browser_book_snapshot_is_bounded_and_detached(self):
        client = self._synced_kucoin_client()
        client.bids = {float(price): float(price) for price in range(1, 31)}
        client.asks = {float(price): float(price) for price in range(31, 61)}
        client.last_sequence_end = 55

        with client._orderbook_lock:
            book = client._browser_book_snapshot_locked(100.0)

        self.assertEqual(len(book["bids"]), 20)
        self.assertEqual(len(book["asks"]), 20)
        self.assertEqual(book["bids"][0]["price"], 30.0)
        self.assertEqual(book["asks"][0]["price"], 31.0)
        client.bids[30.0] = 999.0
        self.assertEqual(book["bids"][0]["size"], 30.0)

    def test_invalid_or_crossed_snapshot_is_not_reported_synced(self):
        client = self._synced_kucoin_client()
        client.bids = {2.0: 1.0}
        client.asks = {1.0: 1.0}

        with client._orderbook_lock:
            book = client._browser_book_snapshot_locked(100.0)

        self.assertEqual(book["dataQuality"], "INVALID")
        self.assertEqual(book["syncState"], "UNSYNCED")

    def test_get_result_exposes_the_saved_market_contract_unchanged(self):
        manager = BotManager()
        captured_at = time.time()
        callback_snapshot = {
            "market_type": "FUTURES",
            "exchange_symbol": "XRPUSDTM",
            "market_timestamp": captured_at,
            "sequence": 12345,
            "price": 0.6124,
            "best_bid": 0.6123,
            "best_ask": 0.6125,
            "spread": 0.0002,
            "order_book": {
                "timestamp": captured_at,
                "sequence": 12345,
                "depth": 1,
                "bids": [{"price": 0.6123, "size": 10.0}],
                "asks": [{"price": 0.6125, "size": 12.0}],
                "dataQuality": "VALID",
                "syncState": "SYNCED",
            },
            "recent_trades": [{
                "symbol": "XRPUSDT",
                "exchangeSymbol": "XRPUSDTM",
                "contextKey": "KUCOIN:FUTURES:XRPUSDTM",
                "tradeId": "trade-1",
                "timestamp": captured_at,
                "price": 0.6124,
                "quantity": 2.0,
                "side": "BUY",
                "sequence": 12344,
            }],
            "trade_stream_ready": True,
        }
        snapshot = {
            "exchange": "kucoin",
            "marketType": callback_snapshot["market_type"],
            "exchangeSymbol": callback_snapshot["exchange_symbol"],
            "timestamp": callback_snapshot["market_timestamp"],
            "sequence": callback_snapshot["sequence"],
            "price": callback_snapshot["price"],
            "bestBid": callback_snapshot["best_bid"],
            "bestAsk": callback_snapshot["best_ask"],
            "spread": callback_snapshot["spread"],
            "dataQuality": "VALID",
            "orderBook": {
                **callback_snapshot["order_book"],
            },
            "recentTrades": [{
                "symbol": "XRPUSDT",
                "exchangeSymbol": "XRPUSDTM",
                "contextKey": "KUCOIN:FUTURES:XRPUSDTM",
                "tradeId": "trade-1",
                "timestamp": captured_at,
                "price": 0.6124,
                "quantity": 2.0,
                "side": "BUY",
                "sequence": 12344,
            }],
            "tradeStreamReady": True,
            "markers": [],
            "markerStatus": "MARKERS_UNAVAILABLE",
        }
        manager._running = True
        manager.market_ready = True
        manager.last_price = snapshot["price"]
        manager.last_update_time = captured_at
        manager._store_market_snapshot(callback_snapshot)

        result = manager.get_result()

        self.assertEqual(result["market"], snapshot)
        self.assertIsNot(result["market"], manager.market_snapshot)
        self.assertNotIn("bids", result["market"])
        self.assertNotIn("asks", result["market"])
        self.assertEqual(result["market"]["recentTrades"], snapshot["recentTrades"])
        self.assertEqual(result["market"]["markers"], [])
        self.assertEqual(result["market"]["markerStatus"], "MARKERS_UNAVAILABLE")

    def test_get_result_market_contract_is_null_safe_before_first_tick(self):
        manager = BotManager()
        manager.exchange_name = "kucoin"
        manager.market_type = "FUTURES"
        manager.orderbook_symbol = "XRPUSDTM"

        market = manager.get_result()["market"]

        self.assertEqual(
            set(market),
            {
                "exchange",
                "marketType",
                "exchangeSymbol",
                "timestamp",
                "sequence",
                "price",
                "bestBid",
                "bestAsk",
                "spread",
                "dataQuality",
                "orderBook",
                "recentTrades",
                "tradeStreamReady",
                "markers",
                "markerStatus",
            },
        )
        self.assertEqual(market["exchange"], "kucoin")
        self.assertEqual(market["marketType"], "FUTURES")
        self.assertEqual(market["exchangeSymbol"], "XRPUSDTM")
        self.assertIsNone(market["timestamp"])
        self.assertIsNone(market["sequence"])
        self.assertIsNone(market["price"])
        self.assertIsNone(market["bestBid"])
        self.assertIsNone(market["bestAsk"])
        self.assertIsNone(market["spread"])
        self.assertEqual(market["dataQuality"], "UNAVAILABLE")
        self.assertEqual(market["orderBook"]["bids"], [])
        self.assertEqual(market["orderBook"]["asks"], [])
        self.assertEqual(market["orderBook"]["syncState"], "UNAVAILABLE")
        self.assertEqual(market["recentTrades"], [])
        self.assertFalse(market["tradeStreamReady"])
        self.assertEqual(market["markers"], [])
        self.assertEqual(market["markerStatus"], "MARKERS_UNAVAILABLE")

    def test_stale_status_changes_quality_without_mixing_snapshot_values(self):
        manager = BotManager()
        manager._running = True
        manager.last_update_time = time.time() - 6
        with manager.market_snapshot_lock:
            manager.market_snapshot = {
                "exchange": "kucoin",
                "marketType": "FUTURES",
                "exchangeSymbol": "XRPUSDTM",
                "timestamp": 100.0,
                "sequence": 99,
                "price": 10.0,
                "bestBid": 9.0,
                "bestAsk": 11.0,
                "spread": 2.0,
                "dataQuality": "VALID",
                "orderBook": {
                    "timestamp": 100.0,
                    "sequence": 99,
                    "depth": 1,
                    "bids": [{"price": 9.0, "size": 1.0}],
                    "asks": [{"price": 11.0, "size": 1.0}],
                    "dataQuality": "VALID",
                    "syncState": "SYNCED",
                },
            }

        market = manager.get_result()["market"]

        self.assertEqual(market["dataQuality"], "STALE")
        self.assertEqual(market["orderBook"]["dataQuality"], "STALE")
        self.assertEqual(
            (
                market["timestamp"],
                market["sequence"],
                market["price"],
                market["bestBid"],
                market["bestAsk"],
                market["spread"],
            ),
            (100.0, 99, 10.0, 9.0, 11.0, 2.0),
        )

    def test_browser_websocket_sends_market_contract_unchanged(self):
        market = {
            "exchange": "kucoin",
            "marketType": "FUTURES",
            "exchangeSymbol": "XRPUSDTM",
            "timestamp": 100.0,
            "sequence": 99,
            "price": 10.0,
            "bestBid": 9.0,
            "bestAsk": 11.0,
            "spread": 2.0,
            "dataQuality": "VALID",
            "orderBook": {
                "timestamp": 100.0,
                "sequence": 99,
                "depth": 1,
                "bids": [{"price": 9.0, "size": 1.0}],
                "asks": [{"price": 11.0, "size": 1.0}],
                "dataQuality": "VALID",
                "syncState": "SYNCED",
            },
        }
        manager = Mock()
        manager.get_result.return_value = {
            "status": "RUNNING",
            "market": market,
        }
        websocket = AsyncMock()

        with (
            patch(
                "backend.api.websocket.get_bot_manager",
                return_value=manager,
            ),
            patch(
                "backend.api.websocket.asyncio.sleep",
                side_effect=WebSocketDisconnect(),
            ),
        ):
            asyncio.run(websocket_endpoint(websocket))

        websocket.accept.assert_awaited_once_with()
        websocket.send_json.assert_awaited_once_with({
            "status": "RUNNING",
            "market": market,
        })
        self.assertEqual(
            manager.set_browser_ws_connection_count.call_args_list,
            [call(1), call(0)],
        )


if __name__ == "__main__":
    unittest.main()
