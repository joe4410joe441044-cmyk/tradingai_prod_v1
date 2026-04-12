# backend/bot_manager.py

# --------------------------
# パス修正（最重要）
# --------------------------
import sys
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# --------------------------
# 通常import
# --------------------------
import threading
import time
import random
from datetime import datetime

from Bot.core.trade_core import TradeCore
from Bot.core.price_manager import PriceManager
from Bot.engine.execution_engine import ExecutionEngine


class BotManager:
    def __init__(self, api_key=None, api_secret=None):
        self.running = False

        # --------------------------
        # ExecutionEngine
        # --------------------------
        self.execution_engine = ExecutionEngine(
            live=False,
            notifier=None
        )

        # TradeCore
        self.core = TradeCore(self.execution_engine)

        # 循環参照
        self.execution_engine.trade_core = self.core

        # PriceManager
        self.price_manager = PriceManager()

        # ログ
        self.logs = []
        self.thread = None

        # 設定
        self.config = {
            "symbol": "BTCUSDT",
            "lot": 0.001
        }

    # --------------------------
    # ログ
    # --------------------------
    def add_log(self, log_type, message):
        try:
            self.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": log_type,
                "message": message
            })
        except Exception:
            pass

    # --------------------------
    # Start / Stop
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
    # メインループ
    # --------------------------
    def run_loop(self):
        while self.running:
            try:
                symbol = self.config.get("symbol", "BTCUSDT")

                price = random.uniform(70000, 75000)

                if price is None:
                    self.add_log("ERROR", "Price fetch failed")
                    time.sleep(1)
                    continue

                # Price update
                self.price_manager.update(symbol, price)

                self.add_log("PRICE", f"{symbol} {price}")

                # TradeCore processing
                if hasattr(self.core, "process_events"):
                    self.core.process_events(self.price_manager.get_all())

                # 仮エントリーイベント
                side = "BUY" if random.random() > 0.5 else "SELL"

                if hasattr(self.core, "emit"):
                    self.core.emit({
                        "type": "ENTRY",
                        "symbol": symbol,
                        "side": side,
                        "qty": self.config.get("lot", 0.001),
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

                time.sleep(1)

            except Exception as e:
                self.add_log("ERROR", str(e))
                time.sleep(1)

    # --------------------------
    # API用
    # --------------------------
    def get_positions(self):
        try:
            result = []

            positions = getattr(self.core, "positions", None)

            if not positions:
                return []

            # dict以外対策
            if not isinstance(positions, dict):
                return []

            for p in positions.values():
                result.append({
                    "pair": getattr(p, "symbol", ""),
                    "side": getattr(p, "trade_type", ""),
                    "entry": getattr(p, "entry_price", 0),
                    "current": getattr(p, "close_price", None) or getattr(p, "entry_price", 0),
                    "pnl": 0,
                    "size": getattr(p, "volume", 0)
                })

            return result

        except Exception:
            return []

    # --------------------------
    # Logs
    # --------------------------
    def get_logs(self):
        try:
            return self.logs[-50:] if self.logs else []
        except Exception:
            return []

    # --------------------------
    # Status（安全版）
    # --------------------------
    def get_status(self):
        try:
            return {
                "running": self.running,
                "thread_alive": self.thread.is_alive() if self.thread else False
            }
        except Exception:
            return {
                "running": False,
                "thread_alive": False
            }

    # --------------------------
    # Running check（重要）
    # --------------------------
    def is_running(self):
        try:
            return bool(self.running and self.thread and self.thread.is_alive())
        except Exception:
            return False