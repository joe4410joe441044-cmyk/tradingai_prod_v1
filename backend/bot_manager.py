import sys
import os
import threading
import time
import random
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from Bot.core.trade_core import TradeCore
from Bot.core.price_manager import PriceManager
from Bot.engine.execution_engine import ExecutionEngine


class BotManager:
    """
    🧠 API専用Facade（安全ゲート）
    - core/engineの違いを吸収
    - APIはここだけ見る
    - 常にfallbackあり（クラッシュ防止）
    """

    def __init__(self):
        self.running = False
        self.thread = None

        # execution engine
        self.execution_engine = ExecutionEngine(
            live=False,
            notifier=None
        )

        # trade core
        self.core = TradeCore(self.execution_engine)
        self.execution_engine.trade_core = self.core

        self.price_manager = PriceManager()

        self.logs = []

        self.config = {
            "symbol": "BTCUSDT",
            "lot": 0.001
        }

    # --------------------------
    # LOG SYSTEM
    # --------------------------
    def add_log(self, log_type, message):
        self.logs.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": log_type,
            "message": message
        })

    # --------------------------
    # START / STOP
    # --------------------------
    def start(self):
        if self.running:
            return

        self.running = True
        self.add_log("SYSTEM", "Bot Started")

        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.add_log("SYSTEM", "Bot Stopped")

    # --------------------------
    # MAIN LOOP
    # --------------------------
    def run_loop(self):
        while self.running:
            try:
                symbol = self.config["symbol"]
                price = random.uniform(70000, 75000)

                self.price_manager.update(symbol, price)
                self.add_log("PRICE", f"{symbol} {price}")

                if hasattr(self.core, "process_events"):
                    self.core.process_events(self.price_manager.get_all())

                side = "BUY" if random.random() > 0.5 else "SELL"

                if hasattr(self.core, "emit"):
                    self.core.emit({
                        "type": "ENTRY",
                        "symbol": symbol,
                        "side": side,
                        "qty": self.config["lot"],
                        "price": price,
                        "sl": price - 100,
                        "tp": price + 100,
                        "strategy": "test",
                        "timeframe": "1m",
                        "latency": 100,
                        "retry": 0,
                        "state_diff": 0,
                        "volatility": 10
                    })

                self._monitor_positions()
                time.sleep(1)

            except Exception as e:
                self.add_log("ERROR", str(e))
                time.sleep(1)

    # --------------------------
    # POSITION MONITOR
    # --------------------------
    def _monitor_positions(self):
        try:
            positions = getattr(self.core, "positions", None)

            if isinstance(positions, dict):
                positions = positions.values()

            if not positions:
                return

            for p in positions:
                if getattr(p, "status", None) == "closed" and not getattr(p, "notified", False):
                    p.notified = True
                    self.add_log("CLOSE", f"{p.symbol} closed")

        except Exception:
            pass

    # --------------------------
    # POSITIONS (SAFE)
    # --------------------------
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

        except Exception:
            return []

    # --------------------------
    # LOGS
    # --------------------------
    def get_logs(self):
        return self.logs[-50:]

    # --------------------------
    # STATUS
    # --------------------------
    def get_status(self):
        return {
            "running": self.running,
            "thread_alive": self.thread.is_alive() if self.thread else False
        }

    # ======================================================
    # 💥 CRITICAL SAFE API LAYER（今回の修正本体）
    # ======================================================

    # --------------------------
    # BALANCE（NEW）
    # --------------------------
    def get_balance(self):
        try:
            if hasattr(self.core, "get_balance"):
                return self.core.get_balance()

            if hasattr(self.execution_engine, "get_balance"):
                return self.execution_engine.get_balance()

            return 0
        except Exception:
            return 0

    # --------------------------
    # PNL
    # --------------------------
    def get_pnl(self):
        try:
            if hasattr(self.core, "get_pnl"):
                return self.core.get_pnl()

            return 0
        except Exception:
            return 0

    # --------------------------
    # PRICE
    # --------------------------
    def get_price(self):
        try:
            logs = reversed(self.logs)
            for l in logs:
                if l["type"] == "PRICE":
                    return float(l["message"].split()[-1])
            return 0
        except Exception:
            return 0

    # --------------------------
    # EQUITY（将来拡張用）
    # --------------------------
    def get_equity(self):
        try:
            balance = self.get_balance()
            pnl = self.get_pnl()
            return balance + pnl
        except Exception:
            return 0

    # --------------------------
    # SAFE CHECK
    # --------------------------
    def is_running(self):
        return bool(self.running and self.thread and self.thread.is_alive())