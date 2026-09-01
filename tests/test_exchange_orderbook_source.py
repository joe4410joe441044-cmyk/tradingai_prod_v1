import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import backend.config as backend_config
from Bot.engine.execution_engine import ExecutionEngine
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
from backend.money_management.enums import (
    MoneyManagementProfile,
    TradingMode,
)
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionOperation,
)
from backend.money_management.loss_execution_integration import (
    LossExecutionAdmissionReason,
    LossExecutionAdmissionResult,
    LossExecutionIntent,
)
from backend.money_management.models import MoneyManagementConfig
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.governance_runtime import governance_state


class StaticPriceManager:

    def __init__(self, price):
        self.price = price

    def get_current_price(self):
        return self.price


class FakeLiveExchange:

    def __init__(self, credentials_ready=True):
        self._credentials_ready = credentials_ready
        self.place_order_calls = []
        self.live_order_allowed = False
        self.live_block_reasons = []

    def credentials_ready(self):
        return self._credentials_ready

    def set_live_order_gate(self, allowed, reasons=None):
        self.live_order_allowed = bool(allowed)
        self.live_block_reasons = list(reasons or [])

    def get_balance(self):
        return 2500.0

    def get_positions(self, symbol=None):
        return None

    def get_symbol_rules(self, symbol):
        return {
            "multiplier": 0.001,
            "min_size": 1,
        }

    def place_order(self, **order):
        self.place_order_calls.append(order)
        return {
            "success": True,
            "raw": {
                "mock": True,
            },
        }


class ExchangeOrderBookSourceTest(unittest.TestCase):

    @staticmethod
    def _allow_money_management_entry(intent):
        if (
            not isinstance(intent, LossExecutionIntent)
            or intent.has_position is not False
            or not isinstance(intent.requested_quantity, Decimal)
            or intent.requested_quantity <= 0
        ):
            raise ValueError("valid new-entry intent required")
        operation = {
            "BUY": LossExecutionOperation.NEW_BUY,
            "SELL": LossExecutionOperation.NEW_SELL,
        }.get(intent.requested_side)
        if operation is None:
            raise ValueError("valid new-entry side required")
        return LossExecutionAdmissionResult(
            operation=operation,
            decision=LossExecutionEntryDecision.ALLOW,
            allowed=True,
            reason=LossExecutionAdmissionReason.ENTRY_ALLOWED,
            generated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            revision=1,
            sequence=1,
            accepted=True,
        )

    @staticmethod
    def _start_config(**overrides):
        values = {
            "symbol": "XRPUSDT",
            "mode": "paper",
            "risk_percent": 1,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 0.5,
            "tp_percent": 1,
            "timeframe": "5m",
            "trailing_stop": True,
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
        self.assertEqual(start_config["position_size"], 100)
        self.assertEqual(start_config["max_drawdown_pct"], 5)
        self.assertEqual(start_config["timeframe"], "5m")
        self.assertTrue(start_config["trailing_stop"])

    def test_bot_manager_start_passes_position_risk_config_to_engine(self):
        manager = BotManager()
        manager.configure_production_ams_read_model(
            lambda: MoneyManagementConfig(
                MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
                TradingMode.PAPER,
                Decimal("1000"), Decimal(".50"), Decimal("100"),
                Decimal("5"), Decimal("20"), Decimal("10"),
                Decimal("5"), False,
            )
        )
        ws = Mock()
        ws.connected = False
        ws.start = Mock()
        config = {
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
            "mode": "paper",
            "risk_percent": 1,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 0.5,
            "tp_percent": 1,
            "timeframe": "5m",
            "trailing_stop": True,
            "leverage": 5,
        }

        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            return_value=ws,
        ) as create_market_ws:
            result = manager.start(config)

        self.assertEqual(result["status"], "started", result)
        self.assertEqual(result["activeSymbol"], "XRPUSDT")
        self.assertEqual(result["symbol"], result["activeSymbol"])
        self.assertEqual(result["selectionMode"], "MANUAL")
        self.assertEqual(manager.activeSymbol, "XRPUSDT")
        self.assertEqual(manager.symbol, manager.activeSymbol)
        self.assertEqual(manager.engine.symbol, manager.activeSymbol)
        self.assertEqual(
            create_market_ws.call_args.kwargs["symbol"],
            manager.activeSymbol,
        )
        self.assertEqual(manager.orderbook_symbol, "XRPUSDTM")
        with self.assertRaisesRegex(
            RuntimeError,
            "RUNNING_SYMBOL_SWITCH_UNSUPPORTED",
        ):
            manager.symbol = "BTCUSDT"
        self.assertEqual(manager.activeSymbol, "XRPUSDT")
        self.assertEqual(manager.engine.config["position_size"], 100)
        self.assertEqual(manager.engine.config["max_drawdown_pct"], 5)
        self.assertEqual(manager.engine.config["tp_percent"], 1)
        self.assertEqual(manager.engine.config["sl_percent"], 0.5)
        self.assertEqual(manager.engine.config["timeframe"], "5m")
        self.assertTrue(manager.engine.config["trailing_stop"])
        self.assertEqual(
            manager.engine.get_risk_state()["positionSize"],
            100,
        )

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

        subscriptions = [
            json.loads(item.args[0]) for item in ws.send.call_args_list
        ]
        self.assertEqual(
            [item["topic"] for item in subscriptions],
            [
                "/contractMarket/level2:XRPUSDTM",
                "/contractMarket/execution:XRPUSDTM",
            ],
        )
        self.assertTrue(all(
            not item["privateChannel"] for item in subscriptions
        ))
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

    def test_kucoin_snapshot_publishes_ready_book_without_cached_diff(self):
        response = Mock()
        response.json.return_value = {
            "data": {
                "sequence": 20,
                "bids": [["0.50", "100"]],
                "asks": [["0.51", "90"]],
            },
        }
        client = KuCoinFuturesOrderBookWS(
            symbol="C98USDT",
            on_update=Mock(),
            runtime_id="runtime-test",
        )

        with patch(
            "backend.market.exchanges.kucoin_market_ws.requests.get",
            return_value=response,
        ):
            synced = client.load_snapshot()

        self.assertTrue(synced)
        client.on_update.assert_called_once()
        symbol, payload, runtime_id = client.on_update.call_args.args
        self.assertEqual(symbol, "C98USDT")
        self.assertEqual(runtime_id, "runtime-test")
        self.assertEqual(payload["exchange_symbol"], "C98USDTM")
        self.assertEqual(payload["sequence"], 20)
        self.assertEqual(payload["order_book"]["dataQuality"], "VALID")
        self.assertTrue(payload["bids"])
        self.assertTrue(payload["asks"])

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

    def _paper_engine(self, price=2.0, **config):
        price_manager = StaticPriceManager(price)
        engine = ExecutionEngine(
            portfolio=PortfolioManager(1000),
            price_manager=price_manager,
        )
        engine.set_execution_entry_guard(
            self._allow_money_management_entry
        )
        engine.symbol = "XRPUSDT"
        engine.set_config({
            "risk_percent": 1,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 1,
            "tp_percent": 10,
            "timeframe": "5m",
            "leverage": 5,
            "trailing_stop": False,
            **config,
        })
        engine.start()
        engine.on_price("XRPUSDT", price)
        return engine, price_manager

    @staticmethod
    def _paper_engine_with_position(
        latest_price=0.0,
        fallback_price=0.0,
        side="BUY",
    ):
        portfolio = PortfolioManager(1000)
        price_manager = StaticPriceManager(fallback_price)
        engine = ExecutionEngine(
            portfolio=portfolio,
            price_manager=price_manager,
        )
        engine.symbol = "XRPUSDT"
        engine.mode = "paper"
        engine.balance = 1000
        engine.initial_equity = 1000
        engine.peak_equity = 1000
        engine.latest_price = latest_price
        engine.unrealized_pnl = 3
        engine.actual_position = {
            "state": "OPEN",
            "side": side,
            "entry_price": 2.0,
            "qty": 10,
            "coin_qty": 10,
            "multiplier": 1.0,
        }
        portfolio.open_position("XRPUSDT", 2.0, 10, side)
        portfolio.open_position("ETHUSDT", 100.0, 1, "BUY")
        return engine, portfolio, price_manager

    def _live_status(
        self,
        *,
        allow_live=True,
        trade_mode="live",
        dry_run=False,
        credentials_ready=True,
        exchange_attached=True,
        balance_check_ok=True,
        position_check_ok=True,
        execution_enabled=True,
        emergency_stop=False,
        running=False,
    ):
        exchange = (
            FakeLiveExchange(
                credentials_ready=credentials_ready
            )
            if exchange_attached
            else None
        )
        engine = ExecutionEngine(
            exchange=exchange,
            portfolio=PortfolioManager(1000),
            price_manager=StaticPriceManager(2.0),
        )
        config = {
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
            "mode": "live",
            "dry_run": dry_run,
            "risk_percent": 1.5,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 1.2,
            "tp_percent": 2.5,
            "timeframe": "1m",
            "leverage": 7,
            "trailing_stop": False,
        }
        engine.symbol = "XRPUSDT"
        engine.set_config(config)
        engine.balance_check_ok = balance_check_ok
        engine.position_check_ok = position_check_ok
        # Live-readiness uses synchronized account evidence, not boolean
        # readiness flags alone.  Populate the same public fields produced by
        # a successful read-only account sync.
        engine.real_balance = 2500.0 if balance_check_ok else None
        engine.real_equity = 2500.0 if balance_check_ok else None
        engine.real_available_balance = (
            2500.0 if balance_check_ok else None
        )
        engine.real_position = [] if position_check_ok else None
        engine.real_position_state = (
            "FLAT" if position_check_ok else "NOT_SYNCED"
        )
        engine.real_account_last_sync = (
            1_700_000_000.0
            if balance_check_ok or position_check_ok
            else None
        )

        bot = BotManager()
        bot.symbol = "XRPUSDT"
        bot.config = dict(config)
        bot.exchange_name = "kucoin"
        bot.orderbook_source = "kucoin_futures"
        bot.orderbook_symbol = "XRPUSDTM"
        bot.engine = engine
        bot._running = running
        bot.latest_runtime_result = {
            "runtimeDebug": {}
        }

        execution_enabled_before = (
            governance_state["execution_enabled"]
        )
        emergency_stop_before = (
            governance_state["emergency_stop"]
        )

        try:
            governance_state["execution_enabled"] = (
                execution_enabled
            )
            governance_state["emergency_stop"] = (
                emergency_stop
            )

            with patch.object(
                backend_config,
                "ALLOW_LIVE",
                allow_live,
            ), patch.object(
                backend_config,
                "TRADE_MODE",
                trade_mode,
            ):
                return bot.get_status()
        finally:
            governance_state["execution_enabled"] = (
                execution_enabled_before
            )
            governance_state["emergency_stop"] = (
                emergency_stop_before
            )

    def test_flatten_paper_position_closes_with_argument_price(self):
        engine, portfolio, _ = self._paper_engine_with_position()

        with patch.object(
            engine,
            "close_position",
            wraps=engine.close_position,
        ) as close_position:
            result = engine.flatten_paper_position(price=2.5)

        close_position.assert_called_once_with(2.5, "EMERGENCY_FLATTEN")
        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "paper")
        self.assertEqual(result["symbol"], "XRPUSDT")
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["flattened"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertFalse(result["skipped"])
        self.assertEqual(result["results"][0]["price"], 2.5)
        self.assertIsNone(engine.actual_position)
        self.assertAlmostEqual(engine.pnl, 5.0)
        self.assertAlmostEqual(engine.balance, 1005.0)
        self.assertAlmostEqual(portfolio.balance, 1005.0)
        self.assertEqual(engine.unrealized_pnl, 0)
        self.assertNotIn("XRPUSDT", portfolio.positions)
        self.assertIn("ETHUSDT", portfolio.positions)
        self.assertEqual(portfolio.realized_pnl, 5.0)

    def test_flatten_paper_position_skips_without_position(self):
        engine, _, _ = self._paper_engine_with_position()
        engine.actual_position = None

        with patch.object(engine, "close_position") as close_position:
            result = engine.flatten_paper_position(price=2.5)

        close_position.assert_not_called()
        self.assertTrue(result["success"])
        self.assertEqual(result["requested"], 0)
        self.assertEqual(result["flattened"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["results"], [])

    def test_flatten_paper_position_uses_latest_price(self):
        engine, _, _ = self._paper_engine_with_position(
            latest_price=2.4,
            fallback_price=2.8,
        )

        with patch.object(
            engine,
            "close_position",
            wraps=engine.close_position,
        ) as close_position:
            with patch.object(
                engine,
                "get_price",
                wraps=engine.get_price,
            ) as get_price:
                result = engine.flatten_paper_position()

        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["price"], 2.4)
        close_position.assert_called_once_with(2.4, "EMERGENCY_FLATTEN")
        get_price.assert_not_called()

    def test_flatten_paper_position_falls_back_to_get_price(self):
        engine, _, _ = self._paper_engine_with_position(
            latest_price=0,
            fallback_price=2.6,
        )

        with patch.object(
            engine,
            "close_position",
            wraps=engine.close_position,
        ) as close_position:
            with patch.object(
                engine,
                "get_price",
                wraps=engine.get_price,
            ) as get_price:
                result = engine.flatten_paper_position()

        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["price"], 2.6)
        close_position.assert_called_once_with(2.6, "EMERGENCY_FLATTEN")
        get_price.assert_called_once()

    def test_flatten_paper_position_fails_without_valid_price(self):
        for invalid_price in [None, 0, -1, float("nan"), float("inf")]:
            with self.subTest(price=invalid_price):
                engine, _, _ = self._paper_engine_with_position(
                    latest_price=0,
                    fallback_price=0,
                )
                position_before = dict(engine.actual_position)

                result = engine.flatten_paper_position(price=invalid_price)

                self.assertFalse(result["success"])
                self.assertEqual(result["requested"], 1)
                self.assertEqual(result["flattened"], 0)
                self.assertEqual(result["failed"], 1)
                self.assertFalse(result["skipped"])
                self.assertEqual(result["error"], "INVALID_FLATTEN_PRICE")
                self.assertEqual(engine.actual_position, position_before)

    def test_flatten_paper_position_returns_failure_on_close_exception(self):
        engine, _, _ = self._paper_engine_with_position()

        with patch.object(
            engine,
            "close_position",
            side_effect=RuntimeError("close failed"),
        ) as close_position:
            result = engine.flatten_paper_position(price=2.5)

        close_position.assert_called_once_with(2.5, "EMERGENCY_FLATTEN")
        self.assertFalse(result["success"])
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["flattened"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertIn("close failed", result["error"])
        self.assertIsNotNone(result["position_after"])
        self.assertIsNotNone(engine.actual_position)

    def test_flatten_paper_position_is_idempotent(self):
        engine, _, _ = self._paper_engine_with_position()

        first = engine.flatten_paper_position(price=2.5)
        balance_after_first = engine.balance
        pnl_after_first = engine.pnl
        second = engine.flatten_paper_position(price=3.0)

        self.assertTrue(first["success"])
        self.assertEqual(first["flattened"], 1)
        self.assertTrue(second["success"])
        self.assertEqual(second["requested"], 0)
        self.assertEqual(second["flattened"], 0)
        self.assertTrue(second["skipped"])
        self.assertEqual(engine.balance, balance_after_first)
        self.assertEqual(engine.pnl, pnl_after_first)

    def test_position_size_reaches_paper_qty_and_zero_fallback(self):
        engine, _ = self._paper_engine(price=2.0)

        preview = engine.get_result()["preview"]
        self.assertEqual(preview["sizing_mode"], "fixed_position_size")
        self.assertEqual(preview["position_size"], 100)
        self.assertEqual(preview["qty"], 50)

        engine.submit_signal({"id": 1001, "side": "BUY"})

        self.assertEqual(engine.actual_position["coin_qty"], 50)
        self.assertEqual(engine.actual_position["position_size"], 100)
        self.assertEqual(engine.get_risk_state()["realQty"], 50)
        self.assertEqual(engine.get_risk_state()["notional"], 100)

        fallback, _ = self._paper_engine(
            price=2.0,
            position_size=0,
            risk_percent=1,
            leverage=5,
        )

        fallback_preview = fallback.get_result()["preview"]
        self.assertEqual(fallback_preview["sizing_mode"], "risk_percent")
        self.assertEqual(fallback_preview["position_size"], 10)
        self.assertEqual(fallback_preview["qty"], 5)
        self.assertEqual(fallback_preview["required_margin"], 2)

    def test_tp_sl_prices_and_paper_close_are_direction_aware(self):
        long_engine, long_price = self._paper_engine(price=2.0)
        long_engine.submit_signal({"id": 2001, "side": "BUY"})

        self.assertAlmostEqual(long_engine.actual_position["sl"], 1.98)
        self.assertAlmostEqual(long_engine.actual_position["tp"], 2.2)

        long_price.price = 2.2
        long_engine.on_price("XRPUSDT", 2.2)

        self.assertIsNone(long_engine.actual_position)
        self.assertAlmostEqual(long_engine.pnl, 10)

        short_engine, short_price = self._paper_engine(price=2.0)
        short_engine.submit_signal({"id": 2002, "side": "SELL"})

        self.assertAlmostEqual(short_engine.actual_position["sl"], 2.02)
        self.assertAlmostEqual(short_engine.actual_position["tp"], 1.8)

        short_price.price = 1.8
        short_engine.on_price("XRPUSDT", 1.8)

        self.assertIsNone(short_engine.actual_position)
        self.assertAlmostEqual(short_engine.pnl, 10)

    def test_trailing_stop_only_moves_in_favorable_direction(self):
        disabled, disabled_price = self._paper_engine(
            price=2.0,
            trailing_stop=False,
            tp_percent=20,
        )
        disabled.submit_signal({"id": 3001, "side": "BUY"})
        original_sl = disabled.actual_position["sl"]

        disabled_price.price = 2.1
        disabled.on_price("XRPUSDT", 2.1)

        self.assertEqual(disabled.actual_position["sl"], original_sl)

        long_engine, long_price = self._paper_engine(
            price=2.0,
            trailing_stop=True,
            tp_percent=20,
        )
        long_engine.submit_signal({"id": 3002, "side": "BUY"})

        long_price.price = 2.1
        long_engine.on_price("XRPUSDT", 2.1)
        trailed_sl = long_engine.actual_position["sl"]
        self.assertGreater(trailed_sl, 1.98)

        long_price.price = 2.09
        long_engine.on_price("XRPUSDT", 2.09)
        self.assertEqual(long_engine.actual_position["sl"], trailed_sl)

        short_engine, short_price = self._paper_engine(
            price=2.0,
            trailing_stop=True,
            tp_percent=20,
        )
        short_engine.submit_signal({"id": 3003, "side": "SELL"})

        short_price.price = 1.9
        short_engine.on_price("XRPUSDT", 1.9)
        short_trailed_sl = short_engine.actual_position["sl"]
        self.assertLess(short_trailed_sl, 2.02)

        short_price.price = 1.91
        short_engine.on_price("XRPUSDT", 1.91)
        self.assertEqual(short_engine.actual_position["sl"], short_trailed_sl)

    def test_max_drawdown_blocks_runtime_and_surfaces_status_debug(self):
        engine, _ = self._paper_engine(price=2.0)
        engine.submit_signal({"id": 4001, "side": "BUY"})
        engine.update_drawdown_state(940)

        risk_state = engine.get_risk_state()
        self.assertTrue(risk_state["riskTradingDisabled"])
        self.assertEqual(risk_state["riskBlockReason"], "MAX_DRAWDOWN")

        execution_enabled_before = governance_state["execution_enabled"]
        governance_state["execution_enabled"] = True

        try:
            runtime = ExecutionRuntime()
            runtime.set_engine(engine)

            permission = runtime.evaluate_execution_permission(
                {
                    "executionAllowed": True,
                    "direction": "LONG",
                    "edge": 0.9,
                    "confidence": 0.9,
                    "risk": 0.1,
                },
                {"executionAllowed": True, "reason": None},
                canonical_direction="LONG",
            )
            runtime_state = runtime.build_execution_runtime_state({
                "executionAllowed": False,
                "reason": "MAX_DRAWDOWN",
            })
        finally:
            governance_state["execution_enabled"] = execution_enabled_before

        self.assertFalse(permission["executionAllowed"])
        self.assertEqual(permission["reason"], "MAX_DRAWDOWN")
        self.assertEqual(
            runtime_state["tradeSettings"]["timeframe"],
            "5m",
        )
        self.assertEqual(
            runtime_state["tradeSettings"]["leverage"],
            5,
        )

        bot = BotManager()
        bot.engine = engine
        bot.symbol = "XRPUSDT"
        bot.config = dict(engine.config)
        bot.exchange_name = "kucoin"
        bot.orderbook_source = "kucoin_futures"
        bot.orderbook_symbol = "XRPUSDTM"
        bot._running = True
        bot.latest_runtime_result = {"runtimeDebug": {}}
        bot.attach_orderbook_runtime_debug(bot.latest_runtime_result)

        status = bot.get_status()
        response = StatusResponse(**status)
        runtime_debug = status["latestRuntimeResult"]["runtimeDebug"]

        self.assertEqual(response.position_size, 100)
        self.assertEqual(response.max_drawdown_pct, 5)
        self.assertFalse(response.trailing_stop)
        self.assertEqual(response.real_qty, 50)
        self.assertEqual(response.notional, 100)
        self.assertEqual(response.active_position_qty, 50)
        self.assertEqual(response.active_position_notional, 100)
        self.assertEqual(response.risk_block_reason, "MAX_DRAWDOWN")
        self.assertEqual(status["risk_state"]["riskBlockReason"], "MAX_DRAWDOWN")
        self.assertEqual(status["risk_state"]["realQty"], 50)
        self.assertEqual(status["risk_state"]["notional"], 100)
        self.assertEqual(
            runtime_debug["riskState"]["riskBlockReason"],
            "MAX_DRAWDOWN",
        )
        self.assertEqual(runtime_debug["riskState"]["realQty"], 50)
        self.assertEqual(runtime_debug["riskState"]["notional"], 100)
        self.assertIn("riskConfig", runtime_debug)
        self.assertIn("riskState", runtime_debug)

    def test_live_readiness_blocks_until_all_gates_are_ready(self):
        cases = [
            (
                "allow_live_false",
                {"allow_live": False},
                "LIVE_NOT_ENABLED",
            ),
            (
                "dry_run_true",
                {"dry_run": True},
                "DRY_RUN_ACTIVE",
            ),
            (
                "credentials_missing",
                {"credentials_ready": False},
                "KUCOIN_CREDENTIALS_MISSING",
            ),
            (
                "execution_disabled",
                {"execution_enabled": False},
                "EXECUTION_DISABLED",
            ),
            (
                "emergency_stop",
                {"emergency_stop": True},
                "EMERGENCY_STOP_ACTIVE",
            ),
        ]

        for name, overrides, expected_reason in cases:
            with self.subTest(name=name):
                status = self._live_status(**overrides)

                self.assertFalse(status["realOrderAllowed"])
                self.assertFalse(status["real_order_allowed"])
                self.assertFalse(status["liveReadiness"]["ready"])
                self.assertIn(
                    expected_reason,
                    status["liveBlockReasons"],
                )

        ready_status = self._live_status()
        response = StatusResponse(**ready_status)

        self.assertTrue(response.realOrderAllowed)
        self.assertTrue(ready_status["real_order_allowed"])
        self.assertEqual(response.executionMode, "LIVE")
        self.assertEqual(ready_status["liveBlockReasons"], [])
        self.assertTrue(ready_status["liveReadiness"]["ready"])

    def test_live_readiness_surfaces_in_status_and_runtime_debug(self):
        status = self._live_status(
            allow_live=False,
            running=True,
        )
        runtime_debug = (
            status["latestRuntimeResult"]["runtimeDebug"]
        )

        self.assertIn("liveReadiness", status)
        self.assertIn("liveBlockReasons", status)
        self.assertIn("liveReadiness", runtime_debug)
        self.assertIn("liveBlockReasons", runtime_debug)
        self.assertFalse(status["exchangeClientReady"] is None)
        self.assertTrue(status["exchangeAuthReady"])
        self.assertTrue(status["balanceCheckOk"])
        self.assertTrue(status["positionCheckOk"])
        self.assertFalse(status["realOrderAllowed"])
        self.assertIn(
            "LIVE_NOT_ENABLED",
            runtime_debug["liveBlockReasons"],
        )

    def test_live_order_submit_is_not_called_when_not_ready(self):
        exchange = FakeLiveExchange()
        engine = ExecutionEngine(
            exchange=exchange,
            portfolio=PortfolioManager(1000),
            price_manager=StaticPriceManager(2.0),
        )
        engine.symbol = "XRPUSDT"
        engine.set_config({
            "symbol": "XRPUSDT",
            "mode": "live",
            "dry_run": False,
            "risk_percent": 1,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 1,
            "tp_percent": 2,
            "timeframe": "1m",
            "leverage": 5,
            "trailing_stop": False,
        })
        engine.start()
        engine.on_price("XRPUSDT", 2.0)

        execution_enabled_before = (
            governance_state["execution_enabled"]
        )
        emergency_stop_before = (
            governance_state["emergency_stop"]
        )

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False

            with patch.object(
                backend_config,
                "ALLOW_LIVE",
                False,
            ), patch.object(
                backend_config,
                "TRADE_MODE",
                "live",
            ):
                engine.submit_signal({
                    "id": 5001,
                    "side": "BUY",
                })
        finally:
            governance_state["execution_enabled"] = (
                execution_enabled_before
            )
            governance_state["emergency_stop"] = (
                emergency_stop_before
            )

        self.assertEqual(exchange.place_order_calls, [])
        self.assertEqual(
            engine.last_order_blocked_reason,
            "LIVE_NOT_READY",
        )
        self.assertIn(
            "LIVE_NOT_ENABLED",
            engine.last_live_block_reasons,
        )

    def test_status_and_runtime_debug_expose_orderbook_context(self):
        bot = BotManager()
        context = ExchangeFactory.describe_orderbook(
            "kucoin",
            "XRPUSDT",
        )
        bot.symbol = "XRPUSDT"
        bot.config = {
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
            "mode": "paper",
            "risk_percent": 1.25,
            "sl_percent": 0.75,
            "tp_percent": 1.5,
            "leverage": 3,
            "timeframe": "5m",
        }
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

        self.assertEqual(response.activeSymbol, "XRPUSDT")
        self.assertEqual(response.symbol, response.activeSymbol)
        self.assertEqual(response.selectionMode, "MANUAL")
        self.assertEqual(response.exchange, "kucoin")
        self.assertEqual(response.orderbookSource, "kucoin_futures")
        self.assertEqual(response.orderbookSymbol, "XRPUSDTM")
        self.assertEqual(response.risk_percent, 1.25)
        self.assertEqual(response.leverage, 3)
        self.assertEqual(response.timeframe, "5m")
        self.assertEqual(
            response.tradeSettings["symbol"],
            "XRPUSDT",
        )
        self.assertEqual(
            response.tradeSettings["timeframe"],
            "5m",
        )
        self.assertEqual(
            response.tradeSettings["sl_percent"],
            0.75,
        )
        self.assertEqual(
            running_status["trade_settings"]["tp_percent"],
            1.5,
        )
        runtime_debug = (
            running_status["latestRuntimeResult"]["runtimeDebug"]
        )
        self.assertEqual(
            runtime_debug["momentumTrace"],
            {"sourceValue": 0.25},
        )
        self.assertEqual(runtime_debug["exchange"], "kucoin")
        self.assertEqual(
            runtime_debug["orderbookSource"],
            "kucoin_futures",
        )
        self.assertEqual(
            runtime_debug["orderbookSymbol"],
            "XRPUSDTM",
        )
        self.assertIn("riskConfig", runtime_debug)
        self.assertIn("riskState", runtime_debug)
        self.assertEqual(
            runtime_debug["tradeSettings"]["risk_percent"],
            1.25,
        )
        self.assertEqual(
            runtime_debug["tradeSettings"]["timeframe"],
            "5m",
        )


if __name__ == "__main__":
    unittest.main()
