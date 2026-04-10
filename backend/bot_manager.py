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

from Bot.core.trade_core import TradeCore, StrategyContext
from Bot.core.price_manager import PriceManager

# ★ ExecutionEngineを正しく使う
from Bot.engine.execution_engine import ExecutionEngine


class BotManager:
    def __init__(self, api_key=None, api_secret=None):
        self.running = False

        # --------------------------
        # ExecutionEngine（正しい実行層）
        # --------------------------
        self.execution_engine = ExecutionEngine(
            live=False,   # ← 本番にするなら True
            notifier=None
        )

        # TradeCore に ExecutionEngine を渡す
        self.core = TradeCore(self.execution_engine)

        # ★ 循環参照（重要）
        self.execution_engine.trade_core = self.core

        # PriceManager 初期化
        self.price_manager = PriceManager()

        # ログ、スレッド
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
        self.logs.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": log_type,
            "message": message
        })

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
            symbol = self.config["symbol"]

            # 価格取得（PriceManager経由想定）
            price = random.uniform(70000, 75000)  # ← 仮（Binanceに戻すならここ差し替え）

            if price is None:
                self.add_log("ERROR", "Price fetch failed")
                time.sleep(1)
                continue

            # 価格更新
            self.price_manager.update(symbol, price)

            self.add_log("PRICE", f"{symbol} {price}")

            # ポジション管理
            self.core.check_orders(self.price_manager.get_all())

            # 仮エントリー（テスト戦略）
            ctx = StrategyContext(
                strategy_name="test",
                trade_type="BUY" if random.random() > 0.5 else "SELL",
                entry_price=price,
                stop_loss_price=price - 100,
                take_profit_price=price + 100
            )

            # ★ 正しい実行ルート（ExecutionEngine経由）
            self.core.try_enter(ctx, volume=self.config["lot"])

            time.sleep(1)

    # --------------------------
    # API用
    # --------------------------
    def get_positions(self):
        result = []

        for p in self.core.positions:
            result.append({
                "pair": p.symbol,
                "side": p.trade_type,
                "entry": p.entry_price,
                "current": p.close_price or p.entry_price,
                "pnl": 0,
                "size": p.volume
            })

        return result

    def get_logs(self):
        return self.logs[-50:]

    def get_status(self):
        return {"running": self.running}