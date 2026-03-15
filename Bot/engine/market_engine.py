# Bot/engine/market_engine.py
import pandas as pd
import time
import random

class MarketEngine:
    """
    Market Data Engine
    価格データを Strategy に渡す本番用
    """

    def __init__(self, trade_core=None, logger=None, notifier=None):
        """
        trade_core : TradeCore オブジェクト
        logger     : BotLogger オブジェクト（任意）
        notifier   : TelegramNotifier オブジェクト（任意）
        """
        self.trade_core = trade_core
        self.logger = logger
        self.notifier = notifier

        # OHLCデータ
        self.m15 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        self.h1 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])

        # 前足終値
        self.prev_close = None

        # ループ制御
        self.running = False

        if self.logger:
            self.logger.info("MarketEngine initialized")
        if self.notifier:
            self.notifier.send("MarketEngine initialized")

    # ---------------------------------
    # Tick受信
    # ---------------------------------
    def on_market_tick(self, price):
        try:
            price = float(price)
        except Exception:
            if self.logger:
                self.logger.warning(f"Invalid price received: {price}")
            return

        market_data = {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "prev_close": self.prev_close
        }

        # Strategy 更新
        if self.trade_core and hasattr(self.trade_core, 'strategy_wrapper'):
            for strategy in self.trade_core.strategy_wrapper.strategies:
                strategy.update(market_data)

        # TradeCore へのデータ通知
        if self.trade_core and hasattr(self.trade_core, 'on_market_data'):
            self.trade_core.on_market_data(market_data)

        # 前足終値更新
        self.prev_close = price

        if self.logger:
            self.logger.info(f"Market tick processed: {price}")

    # ---------------------------------
    # run() ループ（本番はリアルデータ取得に置き換え）
    # ---------------------------------
    def run(self):
        if self.logger:
            self.logger.info("MarketEngine run loop started")

        self.running = True
        while self.running:
            # 仮のダミー価格生成（本番はリアルデータ）
            price = 2000 + random.random() * 10
            self.on_market_tick(price)
            time.sleep(1)  # 本番は適切な間隔に変更