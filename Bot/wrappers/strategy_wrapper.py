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
        self.on_entry = None  # 互換用（現在未使用）

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
                # ★ 完全統一済みフロー
                self.trade_core.try_enter(signal)

            except Exception as e:
                logging.error(f"TradeCore error: {e}")

    # ---------------------------------
    # テストシグナル用
    # ---------------------------------
    def on_test_signal(self, trade_type, price, sl, tp, volume):

        try:
            signal = {
                "symbol": "BTCUSDT",
                "side": trade_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "qty": volume,
                "strategy": "test",
                "timeframe": "1m"
            }

            self.trade_core.try_enter(signal)

        except Exception as e:
            logging.error(f"[TEST SIGNAL ERROR] {e}")