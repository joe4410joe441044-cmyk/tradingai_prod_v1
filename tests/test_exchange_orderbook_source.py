import json
import unittest
from unittest.mock import Mock, patch

from backend.api.bot_api import StartConfig, StatusResponse, start_bot
from backend.bot_manager.bot_manager import BotManager
from backend.market.exchange_factory import ExchangeFactory
from backend.market.exchanges.binance_market_ws import (
    OrderBookWS as BinanceOrderBookWS,
)
from backend.market.exchanges.kucoin_market_ws import (
    OrderBookWS as KuCoinFuturesOrderBookWS,
    normalize_futures_symbol,
)


class ExchangeOrderBookSourceTest(unittest.TestCase):

    @staticmethod
    def _start_config(**overrides):
        values = {
            "symbol": "XRPUSDT",
            "mode": "paper",
            "risk_percent": 1,
            "sl_percent": 0.5,
            "tp_percent": 1,
            "leverage": 5,
        }
        values.update(overrides)
        return StartConfig(**values)

    def test_exchange_defaults_to_kucoin(self):
        config = self._start_config()

        self.assertEqual(config.exchange.value, "kucoin")
        self.assertEqual(
            ExchangeFactory.describe_orderbook(
                config.exchange.value,
                config.symbol,
            ),
            {
                "exchange": "kucoin",
                "orderbookSource": "kucoin_futures",
                "orderbookSymbol": "XRPUSDTM",
            },
        )

    def test_start_api_passes_normalized_exchange_to_manager(self):
        manager = Mock()
        manager.start.return_value = {"status": "started"}

        with patch(
            "backend.api.bot_api.get_bot_manager",
            return_value=manager,
        ):
            start_bot(self._start_config(exchange="binance"))

        start_config = manager.start.call_args.args[0]
        self.assertEqual(start_config["exchange"], "binance")
        self.assertEqual(start_config["symbol"], "XRPUSDT")

    def test_factory_selects_kucoin_futures_orderbook(self):
        client = ExchangeFactory.create_market_ws(
            exchange="kucoin",
            symbol="XRPUSDT",
            on_update=Mock(),
        )

        self.assertIsInstance(client, KuCoinFuturesOrderBookWS)
        self.assertEqual(client.symbol, "XRPUSDTM")

    def test_factory_selects_binance_orderbook(self):
        client = ExchangeFactory.create_market_ws(
            exchange="BINANCE",
            symbol="XRPUSDT",
            on_update=Mock(),
        )

        self.assertIsInstance(client, BinanceOrderBookWS)
        self.assertEqual(client.symbol, "xrpusdt")
        self.assertIn("xrpusdt@depth", client.url)

    def test_kucoin_symbol_mapping(self):
        self.assertEqual(
            normalize_futures_symbol("XRPUSDT"),
            "XRPUSDTM",
        )
        self.assertEqual(
            normalize_futures_symbol("SOLUSDT"),
            "SOLUSDTM",
        )

    def test_kucoin_subscribes_to_futures_level2_topic(self):
        client = KuCoinFuturesOrderBookWS(
            symbol="XRPUSDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )
        client._start_snapshot_sync = Mock()
        ws = Mock()

        client.on_open(ws)

        subscription = json.loads(ws.send.call_args.args[0])
        self.assertEqual(
            subscription["topic"],
            "/contractMarket/level2:XRPUSDTM",
        )
        self.assertFalse(subscription["privateChannel"])
        client._start_snapshot_sync.assert_called_once_with()

    def test_kucoin_snapshot_tracks_sequence(self):
        response = Mock()
        response.json.return_value = {
            "data": {
                "sequence": 20,
                "bids": [["0.50", "100"]],
                "asks": [["0.51", "90"]],
            },
        }
        client = KuCoinFuturesOrderBookWS(
            symbol="XRPUSDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )

        with patch(
            "backend.market.exchanges.kucoin_market_ws.requests.get",
            return_value=response,
        ):
            client.load_snapshot()

        self.assertTrue(client.snapshot_loaded)
        self.assertTrue(client.is_orderbook_synced)
        self.assertEqual(client.snapshot_sequence, 20)
        self.assertEqual(client.last_sequence_end, 20)

    @staticmethod
    def _kucoin_message(sequence, change):
        return json.dumps({
            "type": "message",
            "subject": "level2",
            "data": {
                "sequence": sequence,
                "change": change,
            },
        })

    @staticmethod
    def _synced_kucoin_client(last_sequence=100):
        client = KuCoinFuturesOrderBookWS(
            symbol="XRPUSDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )
        client.bids = {0.50: 100.0}
        client.asks = {0.51: 90.0}
        client.snapshot_loaded = True
        client.orderbook_initialized = True
        client.is_orderbook_synced = True
        client.snapshot_sequence = last_sequence
        client.last_sequence_end = last_sequence
        return client

    def test_kucoin_drops_old_diff(self):
        client = self._synced_kucoin_client()

        client.on_message(
            Mock(),
            self._kucoin_message(100, "0.50,buy,999"),
        )

        self.assertEqual(client.bids[0.50], 100.0)
        self.assertEqual(client.last_sequence_end, 100)
        self.assertEqual(client.dropped_old_diff_count, 1)
        client.on_update.assert_not_called()

    def test_kucoin_applies_continuous_diff(self):
        client = self._synced_kucoin_client()

        client.on_message(
            Mock(),
            self._kucoin_message(101, "0.50,buy,125"),
        )

        self.assertEqual(client.bids[0.50], 125.0)
        self.assertEqual(client.last_sequence_end, 101)
        self.assertEqual(client.ws_update_count, 1)
        client.on_update.assert_called_once()

    def test_kucoin_callback_keeps_all_local_orderbook_levels(self):
        client = self._synced_kucoin_client()
        client.bids = {
            0.50 - (index * 0.001): float(index + 1)
            for index in range(25)
        }
        client.asks = {
            0.51 + (index * 0.001): float(index + 1)
            for index in range(24)
        }

        client.on_message(
            Mock(),
            self._kucoin_message(101, "0.50,buy,125"),
        )

        payload = client.on_update.call_args.args[1]
        self.assertEqual(len(payload["bids"]), 25)
        self.assertEqual(len(payload["asks"]), 24)
        self.assertEqual(payload["bids"][0.50], 125.0)
        self.assertEqual(payload["asks"], client.asks)

    def test_kucoin_gap_discards_diff_and_starts_resync(self):
        client = self._synced_kucoin_client()
        client._start_snapshot_sync = Mock()

        client.on_message(
            Mock(),
            self._kucoin_message(110, "0.50,buy,999"),
        )

        self.assertEqual(client.bids[0.50], 100.0)
        self.assertEqual(client.last_sequence_end, 100)
        self.assertEqual(client.sequence_gap_count, 1)
        self.assertEqual(
            client.last_sequence_gap["gapSize"],
            9,
        )
        self.assertFalse(client.is_orderbook_synced)
        client._start_snapshot_sync.assert_called_once_with(
            is_resync=True,
        )
        client.on_update.assert_not_called()

        response = Mock()
        response.json.return_value = {
            "data": {
                "sequence": 110,
                "bids": [["0.50", "105"]],
                "asks": [["0.51", "95"]],
            },
        }

        with patch(
            "backend.market.exchanges.kucoin_market_ws.requests.get",
            return_value=response,
        ):
            resynced = client.load_snapshot(is_resync=True)

        self.assertTrue(resynced)
        self.assertTrue(client.is_orderbook_synced)
        self.assertEqual(client.last_sequence_end, 110)
        self.assertEqual(client.bids[0.50], 105.0)
        self.assertEqual(client.resync_count, 1)

    def test_kucoin_replays_cached_diff_after_snapshot(self):
        response = Mock()
        response.json.return_value = {
            "data": {
                "sequence": 100,
                "bids": [["0.50", "100"]],
                "asks": [["0.51", "90"]],
            },
        }
        client = KuCoinFuturesOrderBookWS(
            symbol="XRPUSDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )
        client.cached_diffs = [
            client._parse_diff({
                "sequence": 99,
                "change": "0.49,buy,1",
            }),
            client._parse_diff({
                "sequence": 101,
                "change": "0.50,buy,125",
            }),
        ]
        client.cached_diff_count = 2

        with patch(
            "backend.market.exchanges.kucoin_market_ws.requests.get",
            return_value=response,
        ):
            synced = client.load_snapshot()

        self.assertTrue(synced)
        self.assertTrue(client.is_orderbook_synced)
        self.assertEqual(client.last_sequence_end, 101)
        self.assertEqual(client.bids[0.50], 125.0)
        self.assertEqual(client.dropped_old_diff_count, 1)
        self.assertEqual(client.replayed_diff_count, 1)
        self.assertEqual(
            client.get_orderbook_debug()["pendingCachedDiffCount"],
            0,
        )

    def test_kucoin_pending_gap_marks_next_snapshot_as_resync(self):
        client = self._synced_kucoin_client()
        client.is_orderbook_synced = False
        client.resnapshot_required = True

        with patch(
            "backend.market.exchanges.kucoin_market_ws.threading.Thread"
        ) as thread:
            client._start_snapshot_sync()

        self.assertEqual(
            thread.call_args.kwargs["args"],
            (client._sync_generation, True),
        )

    def test_binance_snapshot_uses_binance_spot_depth(self):
        response = Mock()
        response.json.return_value = {
            "lastUpdateId": 10,
            "bids": [["0.50", "100"]],
            "asks": [["0.51", "90"]],
        }
        client = BinanceOrderBookWS(
            symbol="XRPUSDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )

        with patch(
            "backend.market.exchanges.binance_market_ws.requests.get",
            return_value=response,
        ) as get:
            client.load_orderbook_snapshot()

        url = get.call_args.args[0]
        self.assertIn("api.binance.com/api/v3/depth", url)
        self.assertIn("symbol=XRPUSDT", url)
        self.assertNotIn("kucoin", url.lower())
        self.assertEqual(client.snapshot_sequence, 10)

    def test_status_and_runtime_debug_expose_orderbook_context(self):
        bot = BotManager()
        context = ExchangeFactory.describe_orderbook(
            "kucoin",
            "XRPUSDT",
        )
        bot.symbol = "XRPUSDT"
        bot.exchange_name = context["exchange"]
        bot.orderbook_source = context["orderbookSource"]
        bot.orderbook_symbol = context["orderbookSymbol"]
        bot.latest_runtime_result = {
            "runtimeDebug": {
                "momentumTrace": {"sourceValue": 0.25},
            },
        }

        bot.attach_orderbook_runtime_debug(
            bot.latest_runtime_result
        )
        stopped_status = bot.get_status()

        # Runtime Debug is current-cycle data.  It must not remain current
        # while the bot is stopped, but the same payload must be exposed when
        # this fixture represents a running bot.
        self.assertIsNone(stopped_status["latestRuntimeResult"])

        bot._running = True
        running_status = bot.get_status()
        response = StatusResponse(**running_status)

        self.assertEqual(response.exchange, "kucoin")
        self.assertEqual(response.orderbookSource, "kucoin_futures")
        self.assertEqual(response.orderbookSymbol, "XRPUSDTM")
        self.assertEqual(
            running_status["latestRuntimeResult"]["runtimeDebug"],
            {
                "momentumTrace": {"sourceValue": 0.25},
                "exchange": "kucoin",
                "orderbookSource": "kucoin_futures",
                "orderbookSymbol": "XRPUSDTM",
            },
        )


if __name__ == "__main__":
    unittest.main()
