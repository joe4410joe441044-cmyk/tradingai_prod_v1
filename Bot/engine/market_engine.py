# Bot/engine/market_engine.py

import pandas as pd
from Bot.market.candle_buffer import CandleBuffer


class MarketEngine:
    """
    Market Data Engine
    DataFeedから受け取った市場データをStrategyへ渡す
    """

    def __init__(self, trade_core=None, logger=None, notifier=None):

        self.trade_core = trade_core
        self.logger = logger
        self.notifier = notifier

        # OHLCデータ（将来CandleBufferに完全移行予定）
        self.m15 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        self.h1 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])

        # ★ CandleBuffer管理（通貨ペアごと）
        self.candle_buffers = {}

        if self.logger:
            self.logger.info("MarketEngine initialized")

        if self.notifier:
            try:
                self.notifier.send("MarketEngine initialized")
            except Exception:
                pass

    # ---------------------------------
    # DataFeed からの MarketData
    # ---------------------------------
    def on_market_data(self, market_data):

        try:

            symbol = market_data.get("symbol", "UNKNOWN")
            close_price = float(market_data.get("close", 0))

            if self.logger:
                self.logger.info(f"Market data received {symbol} {close_price}")

            # ---------------------------------
            # CandleBuffer 保存
            # ---------------------------------
            if symbol not in self.candle_buffers:
                self.candle_buffers[symbol] = CandleBuffer()

            self.candle_buffers[symbol].add_candle(market_data)

            # ---------------------------------
            # Strategy 更新
            # ---------------------------------
            if self.trade_core and hasattr(self.trade_core, "strategy_wrapper"):

                for strategy in self.trade_core.strategy_wrapper.strategies:
                    strategy.update(market_data)

            # ---------------------------------
            # TradeCore へ通知
            # ---------------------------------
            if self.trade_core and hasattr(self.trade_core, "on_market_data"):
                self.trade_core.on_market_data(market_data)

        except Exception as e:

            if self.logger:
                self.logger.error(f"MarketEngine data error: {e}")