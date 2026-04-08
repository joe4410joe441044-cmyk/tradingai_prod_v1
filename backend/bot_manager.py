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

# ★ BinanceClient追加
from backend.binance_client import BinanceClient


class BotManager:
    def __init__(self, api_key=None, api_secret=None):
        self.running = False

        # ★ BinanceClient 初期化
        self.binance = BinanceClient(api_key=api_key, api_secret=api_secret)

        # TradeCore に BinanceClient を渡す
        self.core = TradeCore(self.binance)

        # PriceManager 初期化
        self.price_manager = PriceManager()

        # ログ、スレッド
        self.logs = []
        self.thread = None

        # 設定
        self.config = {
            "symbol": "BTCUSDT",
            "lot": 0.001  # 小LOTテスト用
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
    # メインループ（Binance本番化）
    # --------------------------
    def run_loop(self):
        while self.running:
            symbol = self.config["symbol"]

            # ★ Binance価格取得
            price = self.binance.get_price(symbol)

            if price is None:
                self.add_log("ERROR", "Price fetch failed")
                time.sleep(1)
                continue

            # 価格更新
            self.price_manager.update(symbol, price)

            # ログ（価格）
            self.add_log("PRICE", f"{symbol} {price}")

            # 決済チェック
            self.core.check_orders(self.price_manager.get_all())

            # 仮エントリー（戦略テスト用）
            ctx = StrategyContext(
                strategy_name="test",
                trade_type="BUY" if random.random() > 0.5 else "SELL",
                entry_price=price,
                stop_loss_price=price - 100,
                take_profit_price=price + 100
            )

            # 本番注文呼び出し（ロット量を try_enter に渡す）
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