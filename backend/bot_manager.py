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

    def __init__(self):
        self.running = False
        self.thread = None

        # =========================
        # MONITOR ★追加
        # =========================
        self.monitor = None

        # =========================
        # EXCHANGE CLIENTS
        # =========================
        self.clients = {
            "bybit": BybitClient(),
            "binance": BinanceClient(),
            "kucoin": KucoinClient(),
            "okx": OkxClient(),
        }

        # =========================
        # EXECUTION ENGINES
        # =========================
        self.engines = {
            name: ExecutionEngine(
                live=False,
                notifier=None
            )
            for name in self.clients
        }

        # =========================
        # CORE
        # =========================
        self.core = TradeCore(self.engines["bybit"])

        for eng in self.engines.values():
            eng.trade_core = self.core

        self.active_exchange = "bybit"

        # =========================
        # PRICE SYSTEM
        # =========================
        self.price_manager = PriceManager()
        self.latest_prices = {}

        self.logs = []

        self.config = {
            "symbol": "BTCUSDT",
            "lot": 0.001,
            "entry_cooldown_sec": 3
        }

        self._last_entry_time = 0

    # ======================================================
    # 🔥 MONITOR INJECTION（追加）
    # ======================================================
    def set_monitor(self, monitor):

        self.monitor = monitor

        # backend接続
        if self.monitor:
            self.monitor.update_status("backend", True)

        # TradeCore接続
        if hasattr(self.core, "set_monitor"):
            self.core.set_monitor(monitor)

        # ExecutionEngine接続
        for eng in self.engines.values():
            if hasattr(eng, "set_monitor"):
                eng.set_monitor(monitor)

        self.add_log("SYSTEM", "Monitor connected to BotManager")

    # ======================================================
    # EXCHANGE CONTROL
    # ======================================================
    def set_exchange(self, name: str):
        if name in self.clients:
            self.active_exchange = name
            self.add_log("SYSTEM", f"Exchange switched → {name.upper()}")

            if self.monitor:
                self.monitor.log_event("EXCHANGE_SWITCH", {"exchange": name})

    def get_engine(self):
        return self.engines[self.active_exchange]

    def get_client(self):
        return self.clients[self.active_exchange]

    # ======================================================
    # LOG
    # ======================================================
    def add_log(self, t, msg):
        self.logs.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": t,
            "message": msg
        })

        if self.monitor:
            self.monitor.log_event("BOT_LOG", {"type": t, "message": msg})

    # ======================================================
    # START / STOP
    # ======================================================
    def start(self):
        print("START CALLED")

        if self.running:
            return

        self.running = True

        try:
            self.add_log("SYSTEM", "Bot Started")

            if self.monitor:
                self.monitor.log_event("BOT_START", {"status": "ok"})

        except Exception as e:
            print("LOG ERROR:", e)

        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.add_log("SYSTEM", "Bot Stopped")

        if self.monitor:
            self.monitor.log_event("BOT_STOP", {"status": "ok"})

    # ======================================================
    # PRICE INPUT
    # ======================================================
    def set_price(self, symbol: str, price: float):
        self.latest_prices[symbol] = price
        self.price_manager.update(symbol, price)

        if self.monitor:
            self.monitor.log_event("PRICE_UPDATE", {"symbol": symbol, "price": price})

    # ======================================================
    # MAIN LOOP
    # ======================================================
    def run_loop(self):
        print("RUN_LOOP ENTERED")

        while self.running:
            try:
                engine = self.get_engine()
                self.core.execution_engine = engine

                symbol = self.config["symbol"]
                price = self.price_manager.get(symbol)

                if price is None:
                    time.sleep(0.5)
                    continue

                # =========================
                # CORE EVENTS
                # =========================
                try:
                    if hasattr(self.core, "process_events"):
                        self.core.process_events(self.price_manager.get_all())
                except Exception as e:
                    self.add_log("ERROR", f"process_events: {e}")

                    if self.monitor:
                        self.monitor.log_error("process_events", e)

                # =========================
                # ENTRY CONTROL
                # =========================
                now = time.time()

                if now - self._last_entry_time > self.config["entry_cooldown_sec"]:

                    try:
                        if hasattr(self.core, "emit"):
                            self.core.emit({
                                "type": "ENTRY",
                                "symbol": symbol,
                                "side": "BUY",
                                "qty": self.config["lot"],
                                "price": price,
                                "sl": price - 100,
                                "tp": price + 100,
                                "strategy": "test",
                                "timeframe": "1m"
                            })

                            self.add_log("ENTRY", f"{symbol} @ {price}")

                            if self.monitor:
                                self.monitor.log_event("ENTRY_TRIGGER", {
                                    "symbol": symbol,
                                    "price": price
                                })

                            self._last_entry_time = now

                    except Exception as e:
                        self.add_log("ERROR", f"emit crash: {e}")

                        if self.monitor:
                            self.monitor.log_error("emit", e)

                self._monitor_positions()

                time.sleep(1)

            except Exception:
                err = traceback.format_exc()
                self.add_log("ERROR", err)

                if self.monitor:
                    self.monitor.log_error("run_loop", Exception(err))

                time.sleep(1)

    # ======================================================
    # POSITION MONITOR
    # ======================================================
    def _monitor_positions(self):
        try:
            positions = getattr(self.core, "positions", None)

            if isinstance(positions, dict):
                positions = positions.values()

            if not positions:
                return

            for p in positions:
                if getattr(p, "status", None) == "closed":
                    self.add_log("CLOSE", f"{p.symbol} closed")

        except Exception as e:
            self.add_log("ERROR", f"monitor: {e}")

            if self.monitor:
                self.monitor.log_error("position_monitor", e)

    # ======================================================
    # API
    # ======================================================
    def get_positions(self):
        try:
            positions = getattr(self.core, "positions", None)

            if not positions:
                return []

            if isinstance(positions, dict):
                positions = positions.values()

            return [
                {
                    "pair": p.symbol,
                    "side": p.trade_type,
                    "entry": p.entry_price,
                    "current": getattr(p, "close_price", p.entry_price),
                    "size": p.volume,
                    "pnl": 0
                }
                for p in positions
            ]

        except:
            return []

    def get_logs(self):
        return self.logs[-50:]

    def get_status(self):
        return {
            "running": self.running,
            "thread_alive": self.thread.is_alive() if self.thread else False,
            "active_exchange": self.active_exchange
        }

    def get_balance(self):
        try:
            return self.get_engine().get_balance()
        except:
            return 0

    def get_pnl(self):
        try:
            return self.core.get_pnl()
        except:
            return 0

    def get_price(self):
        try:
            symbol = self.config["symbol"]
            return self.price_manager.get(symbol)
        except:
            return 0

    def is_running(self):
        return bool(self.running and self.thread and self.thread.is_alive())