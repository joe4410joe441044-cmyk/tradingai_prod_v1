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
        client.load_snapshot = Mock()
        ws = Mock()

        client.on_open(ws)

        subscription = json.loads(ws.send.call_args.args[0])
        self.assertEqual(
            subscription["topic"],
            "/contractMarket/level2:XRPUSDTM",
        )
        self.assertFalse(subscription["privateChannel"])

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
        self.assertEqual(client.snapshot_sequence, 20)
        self.assertEqual(client.last_sequence_end, 20)

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
        status = bot.get_status()
        response = StatusResponse(**status)

        self.assertEqual(response.exchange, "kucoin")
        self.assertEqual(response.orderbookSource, "kucoin_futures")
        self.assertEqual(response.orderbookSymbol, "XRPUSDTM")
        self.assertEqual(
            status["latestRuntimeResult"]["runtimeDebug"],
            {
                "momentumTrace": {"sourceValue": 0.25},
                "exchange": "kucoin",
                "orderbookSource": "kucoin_futures",
                "orderbookSymbol": "XRPUSDTM",
            },
        )


if __name__ == "__main__":
    unittest.main()
