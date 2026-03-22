# -*- coding: utf-8 -*-
from typing import List
import logging


class StrategyWrapper:
    """
    隍・焚Strategy繧堤ｮ｡逅・＠縲《ignal繧・縺､霑斐☆
    """

    def __init__(self):
        self.strategies: List = []

    # ---------------------------------
    # 謌ｦ逡･逋ｻ骭ｲ
    # ---------------------------------
    def register_strategy(self, strategy):
        self.strategies.append(strategy)

    # ---------------------------------
    # MarketEngine縺九ｉ蜻ｼ縺ｰ繧後ｋ
    # ---------------------------------
    def on_bar(self, market_data):
        """
        蜷Тtrategy繧貞ｮ溯｡後＠縲∵怙蛻昴・signal繧定ｿ斐☆
        """

        for strat in self.strategies:

            try:
                signal = strat.on_bar(market_data)
            except Exception as e:
                logging.error(f"Strategy error: {e}")
                continue

            if signal:
                return signal

        return None
