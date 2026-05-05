# -*- coding: utf-8 -*-

import sys
import os
import threading
import time
import logging

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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

        self.portfolio = PortfolioManager(initial_balance=1000.0)
        self.price_manager = PriceManager()

        self.engine = None
        self.exchange = None
        self.ws = None

        self._engine_lock = threading.Lock()

        print("BOT MANAGER ID:", id(self))

    # =========================
    # Exchange
    # =========================
    def _create_exchange(self):

        from backend.execution.kucoin_trade import KucoinTradeClient

        print("USING KUCOIN FUTURES")

        return KucoinTradeClient(
            api_key=os.getenv("KUCOIN_API_KEY"),
            api_secret=os.getenv("KUCOIN_API_SECRET"),
            passphrase=os.getenv("KUCOIN_API_PASSPHRASE")
        )

    # =========================
    # Engine生成
    # =========================
    def get_engine(self):

        if self.engine:
            return self.engine

        with self._engine_lock:

            if self.engine:
                return self.engine

            print("ENGINE CREATE")

            self.exchange = self._create_exchange()

            self.engine = ExecutionEngine(
                exchange=self.exchange,
                logger=self.logger,
                portfolio=self.portfolio,
                price_manager=self.price_manager
            )

            return self.engine

    # =========================
    # START
    # =========================
    def start(self, config: dict = None):

        with self.lock:

            if self._running:
                print("⚠️ ALREADY RUNNING")
                return {"status": "already_running"}

            print("🚀 START REQUEST")

            if self.ws:
                try:
                    self.ws.stop()
                except Exception:
                    pass
                self.ws = None

            if self.engine:
                try:
                    self.engine.stop()
                except Exception:
                    pass
                self.engine = None

            self._running = True

        if not config or "symbol" not in config:
            raise ValueError("symbol is required")

        symbol = config["symbol"].upper()
        print(f"🎯 SYMBOL LOCKED: {symbol}")

        engine = self.get_engine()

        safe_config = dict(config)
        safe_config.pop("symbol", None)

        if safe_config:
            engine.set_config(safe_config)

        engine.symbol = symbol

        from backend.binance_ws_client import BinanceWSClient

        self.ws = BinanceWSClient(
            price_manager=self.price_manager,
            symbol=symbol,
            engine=engine
        )

        self.ws.start()
        engine.ws_client = self.ws

        result = engine.start()

        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

        return result

    # =========================
    # STOP
    # =========================
    def stop(self):

        with self.lock:
            if not self._running:
                return {"status": "already_stopped"}

            self._running = False

        if self.ws:
            try:
                self.ws.stop()
            except Exception:
                pass
            self.ws = None

        if self.engine:
            try:
                self.engine.stop()
            except Exception:
                pass
            self.engine = None

        return {"status": "stopped"}

    # =========================
    def run_loop(self):
        while self._running:
            time.sleep(0.5)

    # =========================
    # 🔥 修正ポイント（ここが本命）
    # =========================
    def get_status(self):

        if self.engine is None:
            return {"status": "STOPPED"}

        result = self.engine.get_result() or {}

        # 🔥 リアルタイム価格を直接取得
        symbol = getattr(self.engine, "symbol", None)
        price = 0

        if symbol:
            try:
                price = self.price_manager.prices.get(symbol, 0)
            except Exception:
                price = 0

        return {
            **result,
            "price": price,   # ← 強制上書き（最重要）
            "status": result.get("status") or ("RUNNING" if self._running else "STOPPED"),
        }


# =========================
# Singleton
# =========================
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