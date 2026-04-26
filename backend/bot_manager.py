# -*- coding: utf-8 -*-

import sys
import os
import threading
import time
import traceback
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from Bot.core.trade_core import TradeCore
from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.price_manager import PriceManager

from backend.market.binance_ws import BinanceClient

from backend.execution.bybit_trade import BybitTradeClient
from backend.execution.binance_trade import BinanceTradeClient
from backend.execution.kucoin_trade import KucoinTradeClient
from backend.execution.okx_trade import OkxTradeClient

from backend.portfolio.portfolio_manager import PortfolioManager

from backend.ai.trade_brain import TradeBrain
from backend.ai.lstm_model import LSTMModel
from backend.ai.llm_engine import LLMEngine
from backend.ai.feature_engine import FeatureEngine


class BotManager:

    def __init__(self, monitor=None):

        self._running = False
        self.thread = None
        self.lock = threading.Lock()
        self.monitor = monitor

        # Portfolio
        self.portfolio = PortfolioManager(initial_balance=1000.0)
        self.portfolio.set_balance(1000.0)

        # AI
        self.feature_engine = FeatureEngine()

        self.ai = TradeBrain(
            lstm_model=LSTMModel(),
            llm_engine=LLMEngine()
        )

        self._last_ai_event_time = 0

        self.last_result = {
            "realized_pnl": 0.0,
            "positions": {}
        }

        # PRICE
        self.price_manager = PriceManager()
        self.price_manager.subscribe(self._on_price_update)

        self.market_client = BinanceClient(price_manager=self.price_manager)

        if hasattr(self.market_client, "start_ws"):
            self.market_client.start_ws()

        # TRADE CLIENTS
        self.trade_clients = {
            "bybit": BybitTradeClient(),
            "binance": BinanceTradeClient(),
            "kucoin": KucoinTradeClient(),
            "okx": OkxTradeClient(),
        }

        # ENGINES
        self.engines = {
            name: ExecutionEngine(
                live=False,
                notifier=None,
                monitor=self.monitor,
                trade_client=self.trade_clients[name],
                portfolio=self.portfolio
            )
            for name in self.trade_clients
        }

        self.active_exchange = "bybit"
        self.engine = self.engines[self.active_exchange]

        # CORE
        self.core = TradeCore(self.engine)

        for eng in self.engines.values():
            eng.trade_core = self.core

    # =========================
    # PRICE EVENT
    # =========================
    def _on_price_update(self, symbol, price):
        try:
            if not self._running:
                return

            engine = self.get_engine()
            engine.on_price(price)

            candles_map = self.price_manager.get_all()
            candles = candles_map.get(symbol, [])

            if not isinstance(candles, list):
                return

            if len(candles) < 20:
                return

            features = self.feature_engine.build(candles)

            market_data = {
                "symbol": symbol,
                "price": price,
                "features": features,
                "trend": "up" if candles[-1]["close"] > candles[-2]["close"] else "down",
                "volatility": abs(candles[-1]["close"] - candles[-1]["open"])
            }

            signal = self.ai.decide(market_data)

            if signal and signal != "HOLD":
                engine.handle_signal(signal)

            # AI → UI
            if self.monitor:
                events = self.ai.get_events(1)
                if events:
                    latest = events[-1]

                    if latest["time"] != self._last_ai_event_time:
                        self._last_ai_event_time = latest["time"]
                        self.monitor.log_event("AI", latest)

                # ★★★ ここが今回の核心修正 ★★★
                self.monitor.update_dashboard(
                    balance=self.portfolio.get_balance(),
                    equity=self.portfolio.get_equity()
                )

        except Exception as e:
            if self.monitor:
                self.monitor.log_error("PRICE_PUSH", e)

    # ACCESS
    def get_engine(self):
        return self.engines[self.active_exchange]

    def get_trade_client(self):
        return self.trade_clients[self.active_exchange]

    def get_result(self):
        return self.last_result

    # LOG
    def add_log(self, t, msg):
        log = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": t,
            "message": msg
        }

        if self.monitor:
            self.monitor.log_event("BOT_LOG", log)

    # =========================
    # START
    # =========================
    def start(self):

        with self.lock:
            if self._running:
                return {"status": "already_running"}
            self._running = True

        self.engine = self.get_engine()
        self.engine.start()

        self.add_log("SYSTEM", "Bot Started")

        # 初期資金
        self.portfolio.set_balance(1000.0)

        if self.monitor:
            self.monitor.log_event("BOT_START", {})

            # ★★★ ここも追加 ★★★
            self.monitor.update_dashboard(
                status="RUNNING",
                balance=self.portfolio.get_balance(),
                equity=self.portfolio.get_equity()
            )

        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

        return {"status": "started"}

    # STOP
    def stop(self):

        with self.lock:
            if not self._running:
                return {"status": "already_stopped"}
            self._running = False

        for eng in self.engines.values():
            eng.stop()

        self.add_log("SYSTEM", "Bot Stopped")

        if self.monitor:
            self.monitor.log_event("BOT_STOP", {})
            self.monitor.update_dashboard(status="STOPPED")

        return {"status": "stopped"}

    # LOOP
    def run_loop(self):

        while self._running:
            try:
                engine = self.get_engine()
                self.engine = engine
                self.core.execution_engine = engine

                if hasattr(self.core, "process_events"):
                    self.core.process_events(self.price_manager.get_all())

                time.sleep(0.5)

            except Exception:
                err = traceback.format_exc()

                if self.monitor:
                    self.monitor.log_error("BOT_LOOP", err)

                time.sleep(1)

    def is_running(self):
        return self._running