# -*- coding: utf-8 -*-
from typing import List
import logging


class StrategyWrapper:
    """
    EStrategyEsignalE
    """

    def __init__(self):
        self.strategies: List = []

    # ---------------------------------
    # 
    # ---------------------------------
    def register_strategy(self, strategy):
        self.strategies.append(strategy)

    # ---------------------------------
    # MarketEngine
    # ---------------------------------
    def on_bar(self, market_data):
        """
        StrategyEsignal
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