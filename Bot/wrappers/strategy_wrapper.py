from typing import List
import logging


class StrategyWrapper:
    """
    複数Strategyを管理し、signalを1つ返す
    """

    def __init__(self):
        self.strategies: List = []

    # ---------------------------------
    # 戦略登録
    # ---------------------------------
    def register_strategy(self, strategy):
        self.strategies.append(strategy)

    # ---------------------------------
    # MarketEngineから呼ばれる
    # ---------------------------------
    def on_bar(self, market_data):
        """
        各Strategyを実行し、最初のsignalを返す
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