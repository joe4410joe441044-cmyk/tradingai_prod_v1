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

from backend.clients.bybit import BybitClient
from backend.clients.binance import BinanceClient
from backend.clients.kucoin import KucoinClient
from backend.clients.okx import OkxClient


class BotManager:

    def __init__(self, monitor=None):

        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        self.monitor = monitor

        # =========================
        # CLIENTS
        # =========================
        self.clients = {
            "bybit": BybitClient(),
            "binance": BinanceClient(),
            "kucoin": KucoinClient(),
            "okx": OkxClient(),
        }

        # =========================
        # ENGINES
        # =========================
        self.engines = {
            name: ExecutionEngine(
                live=False,
                notifier=None,
                monitor=self.monitor
            )
            for name in self.clients
        }

        for eng in self.engines.values():
            eng.active = False

        # =========================
        # CORE
        # =========================
        self.core = TradeCore(self.engines["bybit"])

        for eng in self.engines.values():
            eng.trade_core = self.core

        self.active_exchange = "bybit"

        # =========================
        # PRICE（🔥最重要）
        # =========================
        self.price_manager = PriceManager()

        # 🔥 Push型接続（ここが核心）
        self.price_manager.subscribe(self._on_price_update)

        # =========================
        # CONFIG
        # =========================
        self.config = {
            "symbol": "BTCUSDT",
            "lot": 0.001,
            "entry_cooldown_sec": 3
        }

    # =========================
    # PRICE EVENT（🔥新規）
    # =========================
    def _on_price_update(self, symbol, price):
        try:
            engine = self.get_engine()

            # Engineへ即時反映
            engine.on_price(price)

            # UI更新
            if self.monitor:
                self.monitor.update_dashboard(price=price)

        except Exception as e:
            if self.monitor:
                self.monitor.log_error("PRICE_PUSH", e)

    # =========================
    # ACCESS
    # =========================
    def get_engine(self):
        return self.engines[self.active_exchange]

    def get_client(self):
        return self.clients[self.active_exchange]

    # =========================
    # LOG
    # =========================
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
            if self.running:
                return {"status": "already_running"}
            self.running = True

        engine = self.get_engine()
        engine.start()

        self.add_log("SYSTEM", "Bot Started")

        if self.monitor:
            self.monitor.log_event("BOT_START", {})
            self.monitor.update_dashboard(
                status="RUNNING",
                connection="ONLINE"
            )

        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

        return {"status": "started"}

    # =========================
    # STOP
    # =========================
    def stop(self):

        with self.lock:
            if not self.running:
                return {"status": "already_stopped"}
            self.running = False

        for eng in self.engines.values():
            eng.stop()

        self.add_log("SYSTEM", "Bot Stopped")

        if self.monitor:
            self.monitor.log_event("BOT_STOP", {})
            self.monitor.update_dashboard(
                status="STOPPED",
                connection="OFFLINE"
            )

        return {"status": "stopped"}

    # =========================
    # LOOP（軽量化済）
    # =========================
    def run_loop(self):

        while self.running:
            try:
                engine = self.get_engine()
                self.core.execution_engine = engine

                # =========================
                # COREのみ（価格はPushで来る）
                # =========================
                try:
                    if hasattr(self.core, "process_events"):
                        self.core.process_events(self.price_manager.get_all())
                except Exception as e:
                    if self.monitor:
                        self.monitor.log_error("CORE", e)

                time.sleep(0.5)

            except Exception:
                err = traceback.format_exc()

                if self.monitor:
                    self.monitor.log_error("BOT_LOOP", err)
                    self.monitor.update_dashboard(connection="ERROR")

                time.sleep(1)

    # =========================
    # STATUS
    # =========================
    def is_running(self):
        return bool(self.running and self.thread and self.thread.is_alive())