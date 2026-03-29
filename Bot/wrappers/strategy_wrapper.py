# -*- coding: utf-8 -*-
from typing import List
import logging


class StrategyWrapper:
    """
    複数Strategyを管理し、
    Signal → TradeCore → ENTRY通知 まで流す
    """

    def __init__(self, trade_core):
        self.trade_core = trade_core
        self.strategies: List = []
        self.on_entry = None  # ENTRY通知フック

    # ---------------------------------
    # Strategy登録
    # ---------------------------------
    def register_strategy(self, strategy):
        self.strategies.append(strategy)

    # ---------------------------------
    # MarketEngineから呼ばれる
    # ---------------------------------
    def on_bar(self, market_data):

        for strat in self.strategies:

            try:
                signal = strat.on_bar(market_data)
            except Exception as e:
                logging.error(f"Strategy error: {e}")
                continue

            if not signal:
                continue

            try:
                ctx = self.trade_core.try_enter(signal)

                if ctx and self.on_entry:
                    self.on_entry(ctx)

            except Exception as e:
                logging.error(f"TradeCore error: {e}")

    # ---------------------------------
    # テストシグナル用
    # ---------------------------------
    def on_test_signal(self, trade_type, price, sl, tp, volume):

        try:
            from Bot.core.trade_core import StrategyContext

            ctx = StrategyContext(
                strategy_name="test",
                trade_type=trade_type,
                entry_price=price,
                stop_loss_price=sl,
                take_profit_price=tp
            )

            result = self.trade_core.try_enter(ctx)

            if result and self.on_entry:
                self.on_entry(result)

        except Exception as e:
            logging.error(f"[TEST SIGNAL ERROR] {e}")