# -*- coding: utf-8 -*-
from typing import List
import logging


class StrategyWrapper:
    """
    複数Strategyを管理し、Signalをまとめて返す
    """

    def __init__(self):
        self.strategies: List = []

    # ---------------------------------
    # Strategy登録
    # ---------------------------------
    def register_strategy(self, strategy):
        self.strategies.append(strategy)

    # ---------------------------------
    # MarketEngineから呼ばれる
    # ---------------------------------
    def on_bar(self, market_data):
        """
        各StrategyからSignalを収集して返す
        return: List[signal]
        """

        signals = []

        for strat in self.strategies:

            try:
                signal = strat.on_bar(market_data)
            except Exception as e:
                logging.error(f"Strategy error: {e}")
                continue

            if signal:
                signals.append(signal)

        return signals