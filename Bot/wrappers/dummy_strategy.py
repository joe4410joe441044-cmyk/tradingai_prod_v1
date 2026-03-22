# -*- coding: utf-8 -*-

from strategies.base_strategy import BaseStrategy
class DummyStrategy:
    """
    MarketEngine繝・せ繝育畑縺ｮ繝繝溘・繧ｹ繝医Λ繝・ず繝ｼ
    on_bar() 縺ｧ蜿励￠蜿悶▲縺溘Ο繝ｼ繧ｽ繧ｯ雜ｳ繧定｡ｨ遉ｺ縺吶ｋ縺縺・
    """
    def on_bar(self, candle):
        print(f"[DummyStrategy] Received candle: {candle}")
