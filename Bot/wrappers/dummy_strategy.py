# -*- coding: utf-8 -*-

from Bot.strategies.base_strategy import BaseStrategy
class DummyStrategy:
    """
    MarketEngineEEE
    on_bar() E
    """
    def on_bar(self, candle):
        print(f"[DummyStrategy] Received candle: {candle}")