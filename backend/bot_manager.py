# -*- coding: utf-8 -*-

import sys
import os
import threading
import time
import logging

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# =========================
# 🔥 正しいimport（ここが本質）
# =========================
from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.price_manager import PriceManager
from backend.portfolio.portfolio_manager import PortfolioManager

from dotenv import load_dotenv
load_dotenv()


class BotManager:

    def __init__(self, monitor=None):

        self._running = False
        self.thread = None
        self.lock = threading.Lock()
        self.monitor = monitor

        self.logger = logging.getLogger(__name__)

        self.config = {
            "exchange": "kucoin"
        }

        self.portfolio = PortfolioManager(initial_balance=1000.0)

        self.price_manager = PriceManager()
        self.price_manager.subscribe(self._on_price_update)

        self.engine = None
        self.exchange = None
        self._engine_lock = threading.Lock()

        print("BOT MANAGER ID:", id(self))

    # =========================
    def _create_exchange(self):

        exchange_name = self.config.get("exchange", "kucoin")

        if exchange_name == "kucoin":
            from backend.execution.kucoin_trade import KucoinTradeClient

            print("USING KUCOIN FUTURES")

            return KucoinTradeClient(
                api_key=os.getenv("KUCOIN_API_KEY"),
                api_secret=os.getenv("KUCOIN_API_SECRET"),
                passphrase=os.getenv("KUCOIN_API_PASSPHRASE")
            )

        else:
            raise Exception(f"Unsupported exchange: {exchange_name}")

    # =========================
    def _create_ws(self):

        try:
            from backend.market.binance_ws import BinanceClient

            symbol = "BTCUSDT"
            if self.engine and hasattr(self.engine, "symbol"):
                symbol = self.engine.symbol

            print(f"🧠 WS SYMBOL: {symbol}")

            ws = BinanceClient(
                price_manager=self.price_manager,
                symbol=symbol,
                engine=self.engine
            )

            ws.start_ws()

            print("✅ WS CREATED")

            return ws

        except Exception as e:
            print("[WS CREATE ERROR]", e)
            return None

    # =========================
    def get_engine(self):

        if self.engine:
            if not hasattr(self.engine, "ws_client") or self.engine.ws_client is None:
                print("⚠️ WS CLIENT MISSING → FIXING")
                self.engine.ws_client = self._create_ws()
            return self.engine

        with self._engine_lock:
            if self.engine:
                return self.engine

            print("ENGINE CREATE")

            self.exchange = self._create_exchange()

            self.engine = ExecutionEngine(
                exchange=self.exchange,
                logger=self.logger,
                portfolio=self.portfolio
            )

            self.engine.ws_client = self._create_ws()

            print("ENGINE ID:", id(self.engine))

        return self.engine

    # =========================
    def _on_price_update(self, symbol, price):

        print("PRICE FLOW OK", symbol, price)

        try:
            engine = self.get_engine()
            engine.on_price(price)
        except Exception as e:
            print("[PRICE PUSH ERROR]", e)

    # =========================
    def start(self):

        with self.lock:
            if self._running:
                return {"status": "already_running"}
            self._running = True

        engine = self.get_engine()
        result = engine.start()

        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

        return result

    # =========================
    def stop(self):

        with self.lock:
            if not self._running:
                return {"status": "already_stopped"}
            self._running = False

        if self.engine:
            self.engine.stop()

        return {"status": "stopped"}

    # =========================
    def run_loop(self):

        while self._running:
            try:
                time.sleep(0.5)
            except Exception:
                time.sleep(1)

    def is_running(self):
        return self._running

    def get_status(self):

        if self.engine is None:
            return {
                "status": "STOPPED",
                "price": 0,
                "balance": 0,
                "pnl": 0,
                "positions": {},
            }

        result = self.engine.get_result()

        return {
            "status": "RUNNING" if self._running else "STOPPED",
            **result
        }


_bot_manager = None
_lock = threading.Lock()


def get_bot_manager():
    global _bot_manager

    if _bot_manager:
        return _bot_manager

    with _lock:
        if _bot_manager is None:
            _bot_manager = BotManager()

    return _bot_manager